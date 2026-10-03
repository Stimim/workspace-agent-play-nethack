"""Reviewed comestibles identified from public names and object glyphs."""

from __future__ import annotations

import re
from typing import Final

from nle import nethack

from nethack_agent.observation import BucStatus, InventoryItem, ProjectedObservation

SAFE_COMESTIBLES: Final = frozenset(
    {
        "food ration",
        "cram ration",
        "lembas wafer",
        "K-ration",
        "C-ration",
        "apple",
        "pear",
        "orange",
        "banana",
        "melon",
        "carrot",
        "sprig of wolfsbane",
        "clove of garlic",
    }
)
_PLURALS: Final = {
    **{name + "s": name for name in SAFE_COMESTIBLES},
    "sprigs of wolfsbane": "sprig of wolfsbane",
    "cloves of garlic": "clove of garlic",
}
_NOUNS: Final = "|".join(
    re.escape(name)
    for name in sorted(SAFE_COMESTIBLES | _PLURALS.keys(), key=len, reverse=True)
)
_DESCRIPTION: Final = re.compile(
    r"^(?:a|an|the|[1-9]\d*) "
    r"(?:(?:blessed|uncursed|cursed|partly eaten|greased|[+-]\d+) )*"
    rf"(?P<name>{_NOUNS})(?: (?:named|called) .+| \([^\n]*\))?$"
)
_FLOOR_PROMPT: Final = re.compile(
    r"^There (?:is |are )(?P<description>.+) here; eat (?:it|one)\? "
    r"\[ynq\] \(n\) $"
)
_LOOK_HERE: Final = re.compile(
    r"(?:^|(?<=[.!?])\s+)You see here (?P<description>.+?)\.(?=$|\s)"
)
_LYCANTHROPY: Final = re.compile(r"\bwere[a-z]+ bites(?:!| you[.!])")


def food_description_name(description: str) -> str | None:
    match = _DESCRIPTION.fullmatch(description)
    if match is None:
        return None
    name = match.group("name")
    return _PLURALS.get(name, name)


def safe_food_name(name: str, observation: ProjectedObservation) -> bool:
    return (
        name in SAFE_COMESTIBLES
        and "hallucinating" not in observation.player.conditions
        and not (name == "clove of garlic" and hero_is_undead(observation))
    )


def hero_is_undead(observation: ProjectedObservation) -> bool:
    if observation.player.hit_dice <= 0:
        return False
    glyph = observation.map.glyph_rows[observation.player.y][observation.player.x]
    if not nethack.glyph_is_monster(glyph):
        return True
    # NetHack 3.6.6's public monster definition flag M2_UNDEAD.
    return bool(nethack.permonst(nethack.glyph_to_mon(glyph)).mflags2 & 0x00000002)


def glyph_food_name(glyph: int) -> str | None:
    if not nethack.glyph_is_object(glyph) or nethack.glyph_is_statue(glyph):
        return None
    index = nethack.glyph_to_obj(glyph)
    if ord(nethack.objclass(index).oc_class) != nethack.FOOD_CLASS:
        return None
    name = nethack.objdescr.from_idx(index).oc_name
    return name if name in SAFE_COMESTIBLES else None


def known_inventory_food(item: InventoryItem) -> str | None:
    if item.object_class != nethack.FOOD_CLASS or not re.fullmatch(
        r"[A-Za-z]", item.letter
    ):
        return None
    name = food_description_name(item.description)
    if name is None or name != glyph_food_name(item.glyph):
        return None
    buc = re.match(
        r"^(?:a|an|the|[1-9]\d*) (blessed|uncursed|cursed)\b", item.description
    )
    expected = BucStatus.UNKNOWN if buc is None else BucStatus(buc.group(1))
    return name if item.buc is expected else None


def safe_inventory_food(observation: ProjectedObservation) -> tuple[InventoryItem, ...]:
    return tuple(
        sorted(
            (
                item
                for item in observation.inventory
                if (name := known_inventory_food(item)) is not None
                and safe_food_name(name, observation)
            ),
            key=lambda item: item.letter,
        )
    )


def is_floor_eat_prompt(message: str) -> bool:
    return _FLOOR_PROMPT.fullmatch(message) is not None


def parse_floor_food_prompt(message: str) -> str | None:
    match = _FLOOR_PROMPT.fullmatch(message)
    return None if match is None else food_description_name(match.group("description"))


def food_underfoot_name(message: str) -> str | None:
    match = _LOOK_HERE.search(message)
    return None if match is None else food_description_name(match.group("description"))


def public_lycanthropy_evidence(message: str) -> bool:
    return "You feel feverish" in message or _LYCANTHROPY.search(message) is not None
