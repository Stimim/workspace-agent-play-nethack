from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Final

from nle import nethack

from nethack_agent.environment import NleObservation

_CONDITION_MASKS: Final = (
    (nethack.BL_MASK_STONE, "petrifying"),
    (nethack.BL_MASK_SLIME, "sliming"),
    (nethack.BL_MASK_STRNGL, "strangled"),
    (nethack.BL_MASK_FOODPOIS, "food_poisoned"),
    (nethack.BL_MASK_TERMILL, "terminally_ill"),
    (nethack.BL_MASK_BLIND, "blind"),
    (nethack.BL_MASK_DEAF, "deaf"),
    (nethack.BL_MASK_STUN, "stunned"),
    (nethack.BL_MASK_CONF, "confused"),
    (nethack.BL_MASK_HALLU, "hallucinating"),
    (nethack.BL_MASK_LEV, "levitating"),
    (nethack.BL_MASK_FLY, "flying"),
    (nethack.BL_MASK_RIDE, "riding"),
)


def _decode_c_string(values: object) -> str:
    raw = values.tobytes()  # type: ignore[attr-defined]
    return raw.split(b"\0", 1)[0].decode("utf-8", errors="replace")


@dataclass(frozen=True, slots=True)
class MapView:
    rows: tuple[str, ...]
    glyph_rows: tuple[tuple[int, ...], ...]
    color_rows: tuple[bytes, ...]
    special_rows: tuple[bytes, ...]


@dataclass(frozen=True, slots=True)
class MapCellChange:
    x: int
    y: int
    character: str
    glyph: int
    color: int
    special: int


@dataclass(frozen=True, slots=True)
class PlayerStats:
    x: int
    y: int
    strength_25: int
    strength_125: int
    dexterity: int
    constitution: int
    intelligence: int
    wisdom: int
    charisma: int
    score: int
    hit_points: int
    max_hit_points: int
    depth: int
    gold: int
    energy: int
    max_energy: int
    armor_class: int
    hit_dice: int
    experience_level: int
    experience_points: int
    turn: int
    hunger: int
    encumbrance: int
    dungeon_number: int
    dungeon_level: int
    alignment: int
    conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PromptState:
    single_character_choice: bool
    text_input: bool
    wait_for_space: bool

    @property
    def active(self) -> bool:
        return self.single_character_choice or self.text_input or self.wait_for_space


@dataclass(frozen=True, slots=True)
class InventoryItem:
    letter: str
    description: str
    glyph: int
    object_class: int


@dataclass(frozen=True, slots=True)
class ProjectedObservation:
    step_index: int
    map: MapView
    changed_cells: tuple[MapCellChange, ...]
    player: PlayerStats
    message: str
    prompt: PromptState
    inventory: tuple[InventoryItem, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "step_index": self.step_index,
            "map": {
                "rows": list(self.map.rows),
                "glyph_rows": [list(row) for row in self.map.glyph_rows],
                "color_rows": [row.hex() for row in self.map.color_rows],
                "special_rows": [row.hex() for row in self.map.special_rows],
            },
            "changed_cells": [asdict(cell) for cell in self.changed_cells],
            "player": asdict(self.player),
            "message": self.message,
            "prompt": asdict(self.prompt),
            "inventory": [asdict(item) for item in self.inventory],
        }


class ObservationProjector:
    """Copies compact public state before NLE reuses its observation buffers."""

    def __init__(self) -> None:
        self._previous_map: MapView | None = None

    def reset(self) -> None:
        self._previous_map = None

    def project(
        self, observation: NleObservation, *, step_index: int
    ) -> ProjectedObservation:
        map_view = MapView(
            rows=tuple(
                bytes(row).decode("ascii", errors="replace")
                for row in observation.chars
            ),
            glyph_rows=tuple(
                tuple(int(glyph) for glyph in row) for row in observation.glyphs
            ),
            color_rows=tuple(bytes(row) for row in observation.colors),
            special_rows=tuple(bytes(row) for row in observation.specials),
        )
        changed_cells = self._changed_cells(map_view)
        self._previous_map = map_view
        return ProjectedObservation(
            step_index=step_index,
            map=map_view,
            changed_cells=changed_cells,
            player=self._player_stats(observation),
            message=_decode_c_string(observation.message),
            prompt=PromptState(
                single_character_choice=bool(observation.misc[0]),
                text_input=bool(observation.misc[1]),
                wait_for_space=bool(observation.misc[2]),
            ),
            inventory=self._inventory(observation),
        )

    def _changed_cells(self, current: MapView) -> tuple[MapCellChange, ...]:
        previous = self._previous_map
        if previous is None:
            return ()
        changes = []
        for y, (
            row,
            old_row,
            glyphs,
            old_glyphs,
            colors,
            old_colors,
            specials,
            old_specials,
        ) in enumerate(
            zip(
                current.rows,
                previous.rows,
                current.glyph_rows,
                previous.glyph_rows,
                current.color_rows,
                previous.color_rows,
                current.special_rows,
                previous.special_rows,
                strict=True,
            )
        ):
            if (
                row == old_row
                and glyphs == old_glyphs
                and colors == old_colors
                and specials == old_specials
            ):
                continue
            changes.extend(
                MapCellChange(x, y, character, glyph, color, special)
                for x, (
                    character,
                    old_character,
                    glyph,
                    old_glyph,
                    color,
                    old_color,
                    special,
                    old_special,
                ) in enumerate(
                    zip(
                        row,
                        old_row,
                        glyphs,
                        old_glyphs,
                        colors,
                        old_colors,
                        specials,
                        old_specials,
                        strict=True,
                    )
                )
                if character != old_character
                or glyph != old_glyph
                or color != old_color
                or special != old_special
            )
        return tuple(changes)

    @staticmethod
    def _player_stats(observation: NleObservation) -> PlayerStats:
        values = observation.blstats
        condition_mask = int(values[nethack.NLE_BL_CONDITION])
        return PlayerStats(
            x=int(values[nethack.NLE_BL_X]),
            y=int(values[nethack.NLE_BL_Y]),
            strength_25=int(values[nethack.NLE_BL_STR25]),
            strength_125=int(values[nethack.NLE_BL_STR125]),
            dexterity=int(values[nethack.NLE_BL_DEX]),
            constitution=int(values[nethack.NLE_BL_CON]),
            intelligence=int(values[nethack.NLE_BL_INT]),
            wisdom=int(values[nethack.NLE_BL_WIS]),
            charisma=int(values[nethack.NLE_BL_CHA]),
            score=int(values[nethack.NLE_BL_SCORE]),
            hit_points=int(values[nethack.NLE_BL_HP]),
            max_hit_points=int(values[nethack.NLE_BL_HPMAX]),
            depth=int(values[nethack.NLE_BL_DEPTH]),
            gold=int(values[nethack.NLE_BL_GOLD]),
            energy=int(values[nethack.NLE_BL_ENE]),
            max_energy=int(values[nethack.NLE_BL_ENEMAX]),
            armor_class=int(values[nethack.NLE_BL_AC]),
            hit_dice=int(values[nethack.NLE_BL_HD]),
            experience_level=int(values[nethack.NLE_BL_XP]),
            experience_points=int(values[nethack.NLE_BL_EXP]),
            turn=int(values[nethack.NLE_BL_TIME]),
            hunger=int(values[nethack.NLE_BL_HUNGER]),
            encumbrance=int(values[nethack.NLE_BL_CAP]),
            dungeon_number=int(values[nethack.NLE_BL_DNUM]),
            dungeon_level=int(values[nethack.NLE_BL_DLEVEL]),
            alignment=int(values[nethack.NLE_BL_ALIGN]),
            conditions=tuple(
                name for mask, name in _CONDITION_MASKS if condition_mask & mask
            ),
        )

    @staticmethod
    def _inventory(observation: NleObservation) -> tuple[InventoryItem, ...]:
        items = []
        for letter, description, glyph, object_class in zip(
            observation.inv_letters,
            observation.inv_strs,
            observation.inv_glyphs,
            observation.inv_oclasses,
            strict=True,
        ):
            letter_value = int(letter)
            if letter_value == 0:
                continue
            items.append(
                InventoryItem(
                    letter=chr(letter_value),
                    description=_decode_c_string(description),
                    glyph=int(glyph),
                    object_class=int(object_class),
                )
            )
        return tuple(items)
