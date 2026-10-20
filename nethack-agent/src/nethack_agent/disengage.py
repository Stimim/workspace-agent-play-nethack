"""Combat-only dust Elbereth, driven solely by recorded native actions.

Expected actions are pure snapshots. Prompt bytes never imply protection: only an
exact LOOK readback does. Budgets belong to the recovery, not exploration rearm.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from nle import nethack

from nethack_agent.decision import ActionIntent, DisengageEvidence
from nethack_agent.navigation import ActionKind, ActionRecord, LevelMemory, Monster
from nethack_agent.observation import ProjectedObservation
from nethack_agent.skills import SkillAction
from nethack_agent.traversal import REACHABLE_DUNGEONS

if TYPE_CHECKING:
    from nethack_agent.environment import LegalAction

TRIGGER_NUMERATOR = 1
TRIGGER_DENOMINATOR = 3
TARGET_NUMERATOR = 3
TARGET_DENOMINATOR = 4
TURN_CAP = 200
NATIVE_RETRY_CAP = 2
PROMPT_ACTION_CAP = 24
NO_HEAL_PERIOD_TURNS = 20
NO_HEAL_PERIOD_CAP = 2

# NetHack 3.6.7 include/monsym.h S_HUMAN and monflag.h M2_MINION.
# NLE exposes public species mlet/mflags2, but not attack arrays or alignment.
_HUMAN_CLASS = chr(53)
_MINION_FLAG = 0x00001000
_IMMUNE_SPECIES = frozenset(
    {
        "minotaur",
        "shopkeeper",
        "guard",
        "aligned priest",
        "high priest",
        "Wizard of Yendor",
        "Angel",
        "Death",
        "Famine",
        "Pestilence",
    }
)
# Source attack arrays contain only AT_NONE, AT_BOOM or NO_ATTK, never an
# active attack: monst.c:147-149,302-310,507-516,1304-1333. This is not an
# allow-list of monsters which can be scared. Never attack these from safety.
_PASSIVE_SPECIES = frozenset(
    {
        "gas spore",
        "floating eye",
        "brown mold",
        "yellow mold",
        "green mold",
        "red mold",
        "acid blob",
        "blue jelly",
        "spotted jelly",
        "shrieker",
    }
)
_PUBLIC_BLIND = re.compile(r"\bblind(?:ed|folded)?\b")
_PUBLIC_ROLE = re.compile(r"\b(?:shopkeeper|vault guard|priest|priestess)\b")


def _public_species(monster: Monster):
    """The glyph's own species, the one authoritative public identity.

    `Monster.name` is a cached description word and may be stale (a
    polymorphed/hallucinated cache entry); classification always uses the
    current glyph, never the cached name.
    """
    if not nethack.glyph_is_monster(monster.glyph):
        return None
    return nethack.permonst(nethack.glyph_to_mon(monster.glyph))


def passive_resting_monster(monster: Monster) -> bool:
    """Public species with no active attack; visibility is not a rest threat."""
    species = _public_species(monster)
    return species is not None and species.mname in _PASSIVE_SPECIES


def elbereth_monster_error(monster: Monster, description: str) -> str | None:
    """Source exclusions from public glyph/description, not hidden monster flags.

    monmove.c:139-181 also excludes shopkeepers/vault guards even if
    polymorphed into another species and non-lawful Angels; NLE exposes no
    public isshk/isgd/alignment signal, so only the ordinary PM_SHOPKEEPER
    and PM_GUARD species and the description's own role words are covered.
    """
    text = description.lower()
    if monster.pet or text.startswith(("peaceful ", "tame ")):
        return None
    species = _public_species(monster)
    if species is None or not text.strip():
        return "unknown_public_monster"
    if passive_resting_monster(monster):
        return None
    if _PUBLIC_BLIND.search(text):
        return "publicly_blind_monster"
    # All non-human minion species in 3.6.7 are the lawful celestial species
    # in monst.c:987-1035 (Angel is immune regardless of actual alignment).
    if (
        species.mlet == _HUMAN_CLASS
        or species.mflags2 & _MINION_FLAG
        or species.mname in _IMMUNE_SPECIES
        or _PUBLIC_ROLE.search(text)
    ):
        return "elbereth_immune_monster"
    return None


_BAD_CONDITIONS = frozenset(
    {"blind", "confused", "stunned", "hallucinating", "levitating", "flying", "riding"}
)
# Only ordinary floor/corridor/doors/stairs; no altar, fountain, grave, throne,
# sink, pool, lava, ice, air, or unknown concealed terrain.
_SAFE_CMAP = frozenset({12, 13, 14, 19, 20, 21, 22, 23, 24})
_READBACK = re.compile(r'You read: "([^"\n]*)"\.')
_TOOL = re.compile(r"What do you want to write with\? \[[^\n]*\]\s*\Z")
_ADD = re.compile(r"Do you want to add to the current engraving\? \[ynq\] \(y\)\s*\Z")
_TEXT = re.compile(r"What do you want to write in the dust here\? ")


class DisengageRecovery:
    def __init__(self) -> None:
        self.fallback_reason: str | None = None
        self._seen: int | None = None
        self._phase: str | None = None
        self._cursor = 0
        self._retries = 0
        self._prompts = 0
        self._turns = 0
        self._no_heal = 0
        self._start = 0
        self._period_turn = 0
        self._period_hp = 0
        self._site: tuple[int, int, int, int] | None = None
        self._valid = False
        # Survives zero-turn LOOK/repair invalidation, never creates quiet rest.
        self._established = False
        self._encounter = False
        self._used = False
        self._threats: frozenset[tuple[int, int, int]] = frozenset()
        self._look_text: str | None = None
        self._last_hp: int | None = None
        self._damage_reason: str | None = None
        self._blind_species: set[str] = set()

    @staticmethod
    def _location(before: ProjectedObservation) -> tuple[int, int, int, int]:
        p = before.player
        return p.dungeon_number, p.dungeon_level, p.x, p.y

    def _stop(self, reason: str, *, invalidate: bool = True) -> None:
        self.fallback_reason = reason
        self._phase = None
        if invalidate:
            self._valid = False
            self._established = False

    def observe(
        self,
        before: ProjectedObservation,
        memory: LevelMemory,
        *,
        prayer_available: bool = False,
    ) -> None:
        if self._seen == before.step_index:
            return
        self._seen = before.step_index
        p = before.player
        hp_dropped = self._last_hp is not None and p.hit_points < self._last_hp
        self._last_hp = p.hit_points
        if hp_dropped and any(
            token in before.message.lower()
            for token in (
                "arrow",
                "bolt",
                "missile",
                "wand",
                "beam",
                "blast",
                "thrown",
                "throws",
                "spits",
                "breathes",
            )
        ):
            self._damage_reason = "ranged_damage"
        descriptions = {
            (c.x, c.y): c.text.lower() for c in before.cell_descriptions or ()
        }
        threats = {
            point: mon
            for point, mon in memory.monsters.items()
            if not mon.pet
            and mon.glyph not in memory.peaceful_glyphs
            and not descriptions.get(point, "").startswith(("peaceful ", "tame "))
            and not passive_resting_monster(mon)
        }
        for point, monster in threats.items():
            text = descriptions.get(point, "")
            named = rf"\b{re.escape(monster.name)} "
            if _PUBLIC_BLIND.search(text) or re.search(
                named + r"(?:is|gets|becomes) blind(?:ed)?\b",
                before.message,
                re.IGNORECASE,
            ):
                self._blind_species.add(monster.name)
            elif re.search(named + r"can see again\b", before.message, re.IGNORECASE):
                self._blind_species.discard(monster.name)
        identities = frozenset((x, y, mon.glyph) for (x, y), mon in threats.items())
        self._threats = identities
        # A combat-established recovery keeps resting on its square until a
        # real exit condition, even after the attackers leave or ambient dust
        # erosion invalidates the engraving (repair happens in place).
        continuing = (
            self._established or self._phase in {"look", "readback"}
        ) and self._location(before) == self._site
        if not threats and not continuing:
            had_encounter = self._encounter
            self._encounter = False
            self._used = False
            self._damage_reason = None
            self._blind_species.clear()
            self._stop("threat_gone")
            if not had_encounter:
                self.fallback_reason = None
            return
        if self._site is not None and self._location(before) != self._site:
            self._stop("left_engraving")
        self._encounter = True
        critical = (
            p.hit_points * TRIGGER_DENOMINATOR <= p.max_hit_points * TRIGGER_NUMERATOR
        )
        if (
            self._phase is None
            and not self._valid
            and not self._used
            and not (critical and not prayer_available)
        ):
            self.fallback_reason = "prayer_available" if critical else None
            return
        point = (p.x, p.y)
        reason = None
        if self._damage_reason is not None:
            reason = self._damage_reason
        elif _BAD_CONDITIONS.intersection(p.conditions):
            reason = "excluded_condition"
        elif p.hit_dice > 0:
            reason = "unsupported_polymorph"
        elif p.encumbrance >= 4:
            reason = "cannot_engrave_while_overtaxed"
        elif p.dungeon_number not in REACHABLE_DUNGEONS:
            reason = "unsupported_branch"
        elif point in memory.shop_cells or memory.temple_entry is not None:
            reason = "shop_or_temple"
        elif not memory.in_bounds(point) or memory.cmap(point) not in _SAFE_CMAP:
            reason = "unsafe_or_unknown_terrain"
        elif any(
            word in descriptions.get(point, "")
            for word in (
                "shop",
                "temple",
                "altar",
                "fountain",
                "grave",
                "water",
                "lava",
            )
        ):
            reason = "excluded_location_description"
        else:
            reason = next(
                (
                    error
                    for pos, monster in threats.items()
                    if (
                        error := elbereth_monster_error(
                            monster, descriptions.get(pos, "")
                        )
                    )
                    is not None
                ),
                None,
            )
            if reason is None and any(
                monster.name in self._blind_species for monster in threats.values()
            ):
                reason = "publicly_blind_monster"
        if reason:
            self._stop(reason)
            return
        if self._phase is not None or self._valid:
            if p.hunger >= 2 and self._phase in {"engrave", "wait"}:
                self._stop("hungry", invalidate=False)
                return
            self._turns = max(self._turns, p.turn - self._start)
            if self._turns >= TURN_CAP:
                self._stop("recovery_turn_budget")
                return
            if self._valid:
                if (
                    p.hit_points * TARGET_DENOMINATOR
                    >= p.max_hit_points * TARGET_NUMERATOR
                ):
                    self._stop("recovered_hp", invalidate=False)
                    return
                if p.hunger >= 2:
                    self._stop("hungry", invalidate=False)
                    return
                if p.turn - self._period_turn >= NO_HEAL_PERIOD_TURNS:
                    self._no_heal = (
                        self._no_heal + 1 if p.hit_points <= self._period_hp else 0
                    )
                    self._period_turn, self._period_hp = p.turn, p.hit_points
                    if self._no_heal >= NO_HEAL_PERIOD_CAP:
                        self._stop("no_healing")
                        return
                if self._phase is None:
                    self._phase = "look"
            return
        if self._used:
            if self.fallback_reason is None:
                self.fallback_reason = "encounter_already_attempted"
            return
        if before.prompt.active:
            self.fallback_reason = "unrelated_prompt"
            return
        self._phase = "engrave"
        self._site = self._location(before)
        self.fallback_reason = None

    def expected(self, before: ProjectedObservation) -> DisengageEvidence | None:
        phase = self._phase
        if phase is None or self._location(before) != self._site:
            return None
        if before.prompt.wait_for_space:
            phase = "more"
        if self._prompts >= PROMPT_ACTION_CAP and phase not in {
            "wait",
            "look",
            "engrave",
        }:
            return None
        if phase in {"engrave", "wait"} and before.player.hunger >= 2:
            return None
        if phase == "wait" and (not self._valid or before.player.hunger >= 2):
            return None
        if phase in {"text", "submit"}:
            match = _TEXT.match(before.message)
            if (
                not before.prompt.text_input
                or match is None
                or before.message[match.end() :] != "Elbereth"[: self._cursor]
            ):
                return None
        command = {
            "engrave": 69,
            "tool": 45,
            "overwrite": 110,
            "submit": 13,
            "more": 13,
            "look": 58,
            "wait": 46,
        }.get(phase)
        if phase == "text":
            command = ord("Elbereth"[self._cursor])
        return DisengageEvidence(
            phase,
            command,
            before.step_index,
            self._start if self._used else before.player.turn,
            before.player.x,
            before.player.y,
            self._cursor,
            self._retries,
            self._prompts,
            min(self._turns, 200),
            self._no_heal,
        )

    def select_action(
        self, before: ProjectedObservation, actions_by_command: dict[int, LegalAction]
    ) -> SkillAction | None:
        evidence = self.expected(before)
        if evidence is None:
            return None
        action = actions_by_command.get(evidence.command)
        if action is None:
            return None
        return SkillAction(
            action.index,
            f"Combat recovery: {evidence.phase}.",
            ActionRecord(
                ActionKind.WAIT if evidence.phase == "wait" else ActionKind.OTHER,
                (before.player.x, before.player.y),
            ),
            ActionIntent(None, None, None, disengage=evidence),
        )

    def protected(self, before: ProjectedObservation) -> bool:
        return self._valid and self._location(before) == self._site

    def no_melee(self, before: ProjectedObservation) -> bool:
        return self.protected(before)

    def blocks_attack(self, command: int, before: ProjectedObservation) -> bool:
        if not self.protected(before):
            return False
        if command in {ord("F"), ord("f"), ord("t"), ord("z"), ord("Z"), 4}:
            return True
        delta = {
            ord("h"): (-1, 0),
            ord("j"): (0, 1),
            ord("k"): (0, -1),
            ord("l"): (1, 0),
            ord("y"): (-1, -1),
            ord("u"): (1, -1),
            ord("b"): (-1, 1),
            ord("n"): (1, 1),
        }.get(command)
        return delta is not None and any(
            (x, y) == (before.player.x + delta[0], before.player.y + delta[1])
            for x, y, _ in self._threats
        )

    def owns_prompt(self, before: ProjectedObservation) -> bool:
        return self._phase is not None and before.prompt.active

    def _readback(self, after: ProjectedObservation) -> None:
        match = _READBACK.search(after.message)
        if match:
            self._look_text = match.group(1)

    def _finish_look(self) -> None:
        if self._look_text == "Elbereth":
            self._valid = True
            self._established = True
            self._phase = "wait"
            # The repair budget bounds consecutive failed writes, not the
            # whole rest: ambient erosion over a long rest is expected.
            self._retries = 0
            self.fallback_reason = None
        elif self._retries < NATIVE_RETRY_CAP:
            self._valid = False
            self._retries += 1
            self._cursor = 0
            self._prompts = 0
            self._phase = "engrave"
            self.fallback_reason = "repair_readback"
        else:
            self._stop("native_retry_budget")

    def advance(
        self, evidence: DisengageEvidence | None, after: ProjectedObservation
    ) -> None:
        if evidence is None:
            # Food, movement, combat, or unrelated commands can erase dust.
            if self._valid:
                self._stop("interrupted_by_other_action")
            return
        if evidence.phase == "engrave" and not self._used:
            self._start = after.player.turn
            self._period_turn = after.player.turn
            self._period_hp = after.player.hit_points
            self._turns = 0
            self._no_heal = 0
            self._retries = 0
        if evidence.phase in {"engrave", "look"}:
            self._prompts = 0
            self._used = True
            self._valid = False
        phase = evidence.phase
        if phase not in {"engrave", "look", "wait"}:
            self._prompts += 1
            if self._prompts >= PROMPT_ACTION_CAP:
                self._stop("prompt_action_budget")
                return
        if phase == "text":
            self._cursor += 1
            self._phase = "submit" if self._cursor == 8 else "text"
            if not after.prompt.text_input:
                self._stop("unexpected_text_prompt_end")
            return
        if phase == "submit":
            self._phase = "look"
        elif phase == "look":
            self._look_text = None
            self._readback(after)
            self._phase = "readback"
        elif phase == "wait":
            if self._last_hp is not None and after.player.hit_points < self._last_hp:
                self._damage_reason = "damage_under_protection"
                self._stop(self._damage_reason)
                return
            # Dust may have eroded during the elapsed turn: always LOOK again.
            self._valid = False
            self._phase = "look"
        elif phase == "more" and self._phase == "readback":
            self._readback(after)
        if after.prompt.wait_for_space:
            return
        if self._phase == "readback":
            self._finish_look()
            return
        if phase in {"engrave", "tool", "overwrite", "more"}:
            message = after.message
            if after.prompt.single_character_choice and _TOOL.fullmatch(message):
                self._phase = "tool"
            elif after.prompt.single_character_choice and _ADD.fullmatch(message):
                self._phase = "overwrite"
            elif after.prompt.text_input and _TEXT.fullmatch(message):
                self._cursor = 0
                self._phase = "text"
            elif self._phase != "look":
                self._stop("unexpected_native_prompt")
