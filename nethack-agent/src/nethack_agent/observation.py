from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Final, Self

from nle import nethack

from nethack_agent.contracts import (
    ContractError,
    array_value,
    boolean_value,
    enum_value,
    integer_value,
    object_value,
    string_value,
)
from nethack_agent.environment import NleObservation
from nethack_agent.menus import PickupMenu, pickup_menu_from_tty, stair_here_from_tty

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

_BOULDER_OBJECT: Final = next(
    index
    for index in range(nethack.NUM_OBJECTS)
    if nethack.objdescr.from_idx(index).oc_name == "boulder"
)
_GHOST_MONSTER_CLASS: Final = nethack.permonst(
    next(
        index
        for index in range(nethack.NUMMONS)
        if nethack.permonst(index).mname == "ghost"
    )
).mlet
_GHOST_MONSTERS: Final = frozenset(
    index
    for index in range(nethack.NUMMONS)
    if nethack.permonst(index).mlet == _GHOST_MONSTER_CLASS
)


def _display_row(
    characters: object,
    glyphs: object,
    *,
    row_index: int,
    player_x: int,
    player_y: int,
) -> str:
    display = bytearray(characters)  # type: ignore[arg-type]
    for x, value in enumerate(glyphs):  # type: ignore[arg-type]
        if row_index == player_y and x == player_x:
            continue
        glyph = int(value)
        if (
            nethack.glyph_is_object(glyph)
            and nethack.glyph_to_obj(glyph) == _BOULDER_OBJECT
        ):
            display[x] = ord("0")
        elif (
            nethack.glyph_is_monster(glyph)
            and nethack.glyph_to_mon(glyph) in _GHOST_MONSTERS
        ):
            display[x] = ord("X")
    return display.decode("ascii", errors="replace")


def _pet_row(glyphs: object) -> bytes:
    return bytes(
        int(bool(nethack.glyph_is_pet(int(glyph))))
        for glyph in glyphs  # type: ignore[union-attr]
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
    # One 0/1 byte per cell from NLE's pet-glyph identity. None means the
    # observation was persisted before pet evidence was recorded: unknown, not
    # "no pets".
    pet_rows: tuple[bytes, ...] | None


@dataclass(frozen=True, slots=True)
class MapCellChange:
    x: int
    y: int
    character: str
    glyph: int
    color: int
    special: int
    # None: recorded before pet evidence existed (unknown).
    pet: bool | None


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


class BucStatus(Enum):
    """Explicit beatitude evidence available in an inventory description."""

    BLESSED = "blessed"
    UNCURSED = "uncursed"
    CURSED = "cursed"
    UNKNOWN = "unknown"


# NLE exposes no separate inventory BUC array. NetHack puts a known beatitude
# adjective at the start of the displayed noun phrase, after only an article or
# stack count. Do not infer it from words elsewhere in an item name.
_BUC_PREFIX: Final = re.compile(
    r"^(?:(?:a|an|the|\d+) )?(blessed|uncursed|cursed)(?: |$)"
)


def _buc_status(description: str) -> BucStatus:
    match = _BUC_PREFIX.match(description)
    return BucStatus.UNKNOWN if match is None else BucStatus(match.group(1))


@dataclass(frozen=True, slots=True)
class InventoryItem:
    letter: str
    description: str
    glyph: int
    object_class: int
    buc: BucStatus

    def __post_init__(self) -> None:
        if not isinstance(self.buc, BucStatus):
            raise TypeError("buc must be a BucStatus")


@dataclass(frozen=True, slots=True)
class CellDescription:
    """Current ordinary look evidence, never remembered monster attitude."""

    x: int
    y: int
    text: str

    def __post_init__(self) -> None:
        integer_value(self.x, "description x", minimum=0)
        integer_value(self.y, "description y", minimum=0)
        string_value(self.text, "cell description", minimum=1, maximum=80)

    @classmethod
    def from_json(cls, value: object) -> Self:
        payload = object_value(value, "cell description", {"x", "y", "text"})
        return cls(payload["x"], payload["y"], payload["text"])


@dataclass(frozen=True, slots=True)
class ProjectedObservation:
    step_index: int
    map: MapView
    changed_cells: tuple[MapCellChange, ...]
    player: PlayerStats
    message: str
    prompt: PromptState
    inventory: tuple[InventoryItem, ...]
    pickup_menu: PickupMenu | None = None
    look_stair: str | None = None
    cell_descriptions: tuple[CellDescription, ...] | None = None

    def __post_init__(self) -> None:
        integer_value(self.step_index, "observation step_index", minimum=0)
        if not isinstance(self.map, MapView):
            raise TypeError("map must be a MapView")
        if not isinstance(self.player, PlayerStats):
            raise TypeError("player must be PlayerStats")
        if not isinstance(self.prompt, PromptState):
            raise TypeError("prompt must be PromptState")
        string_value(self.message, "observation message", maximum=4096)
        if not self.map.rows:
            raise ContractError("observation map must contain at least one row")
        width = len(self.map.rows[0])
        if width == 0 or any(len(row) != width for row in self.map.rows):
            raise ContractError("observation map rows must have one consistent width")
        height = len(self.map.rows)
        for name, rows in (
            ("glyph_rows", self.map.glyph_rows),
            ("color_rows", self.map.color_rows),
            ("special_rows", self.map.special_rows),
            ("pet_rows", self.map.pet_rows),
        ):
            if rows is None:
                continue
            if len(rows) != height or any(len(row) != width for row in rows):
                raise ContractError(f"observation map {name} shape does not match rows")
        if self.map.pet_rows is not None and any(
            value > 1 for row in self.map.pet_rows for value in row
        ):
            raise ContractError("observation map pet_rows values must be 0 or 1")
        if not 0 <= self.player.x < width or not 0 <= self.player.y < height:
            raise ContractError("player coordinates are outside the observation map")
        if not all(isinstance(cell, MapCellChange) for cell in self.changed_cells):
            raise TypeError("changed_cells must contain MapCellChange values")
        if not all(isinstance(item, InventoryItem) for item in self.inventory):
            raise TypeError("inventory must contain InventoryItem values")
        if self.pickup_menu is not None and not isinstance(
            self.pickup_menu, PickupMenu
        ):
            raise TypeError("pickup_menu must be a PickupMenu or None")
        if self.look_stair is not None:
            string_value(
                self.look_stair, "observation look_stair", minimum=1, maximum=40
            )
        if self.cell_descriptions is not None:
            if not isinstance(self.cell_descriptions, tuple) or not all(
                isinstance(cell, CellDescription) for cell in self.cell_descriptions
            ):
                raise TypeError("cell_descriptions must contain CellDescription values")
            coordinates = [(cell.x, cell.y) for cell in self.cell_descriptions]
            if len(set(coordinates)) != len(coordinates) or any(
                not (0 <= x < width and 0 <= y < height) for x, y in coordinates
            ):
                raise ContractError(
                    "cell description coordinates invalid or duplicated"
                )
        for cell in self.changed_cells:
            if not 0 <= cell.x < width or not 0 <= cell.y < height:
                raise ContractError("changed cell coordinates are outside the map")

    def to_json(self) -> dict[str, object]:
        player = asdict(self.player)
        player["conditions"] = list(self.player.conditions)
        return {
            "step_index": self.step_index,
            "map": {
                "rows": list(self.map.rows),
                "glyph_rows": [list(row) for row in self.map.glyph_rows],
                "color_rows": [row.hex() for row in self.map.color_rows],
                "special_rows": [row.hex() for row in self.map.special_rows],
                "pet_rows": (
                    None
                    if self.map.pet_rows is None
                    else [row.hex() for row in self.map.pet_rows]
                ),
            },
            "changed_cells": [asdict(cell) for cell in self.changed_cells],
            "player": player,
            "message": self.message,
            "prompt": asdict(self.prompt),
            "inventory": [
                {
                    "letter": item.letter,
                    "description": item.description,
                    "glyph": item.glyph,
                    "object_class": item.object_class,
                    "buc": item.buc.value,
                }
                for item in self.inventory
            ],
            "pickup_menu": None
            if self.pickup_menu is None
            else self.pickup_menu.to_json(),
            "look_stair": self.look_stair,
            "cell_descriptions": (
                None
                if self.cell_descriptions is None
                else [asdict(cell) for cell in self.cell_descriptions]
            ),
        }

    @classmethod
    def from_json(cls, value: object) -> Self:
        payload = object_value(
            value,
            "observation",
            {
                "step_index",
                "map",
                "changed_cells",
                "player",
                "message",
                "prompt",
                "inventory",
            },
            optional={"pickup_menu", "look_stair", "cell_descriptions"},
        )
        return cls(
            step_index=integer_value(
                payload["step_index"], "observation step_index", minimum=0
            ),
            map=_map_view_from_json(payload["map"]),
            changed_cells=tuple(
                _map_cell_change_from_json(item)
                for item in array_value(
                    payload["changed_cells"], "observation changed_cells"
                )
            ),
            player=_player_stats_from_json(payload["player"]),
            message=string_value(
                payload["message"], "observation message", maximum=4096
            ),
            prompt=_prompt_state_from_json(payload["prompt"]),
            inventory=tuple(
                _inventory_item_from_json(item)
                for item in array_value(payload["inventory"], "observation inventory")
            ),
            pickup_menu=(
                None
                if payload.get("pickup_menu") is None
                else PickupMenu.from_json(payload["pickup_menu"])
            ),
            look_stair=(
                None
                if payload.get("look_stair") is None
                else string_value(
                    payload["look_stair"],
                    "observation look_stair",
                    minimum=1,
                    maximum=40,
                )
            ),
            cell_descriptions=(
                None
                if payload.get("cell_descriptions") is None
                else tuple(
                    CellDescription.from_json(cell)
                    for cell in array_value(
                        payload["cell_descriptions"], "cell_descriptions"
                    )
                )
            ),
        )


_PLAYER_FIELDS: Final = (
    "x",
    "y",
    "strength_25",
    "strength_125",
    "dexterity",
    "constitution",
    "intelligence",
    "wisdom",
    "charisma",
    "score",
    "hit_points",
    "max_hit_points",
    "depth",
    "gold",
    "energy",
    "max_energy",
    "armor_class",
    "hit_dice",
    "experience_level",
    "experience_points",
    "turn",
    "hunger",
    "encumbrance",
    "dungeon_number",
    "dungeon_level",
    "alignment",
    "conditions",
)


def _map_view_from_json(value: object) -> MapView:
    # `pet_rows` is absent from observations persisted before pet evidence
    # existed; absent and null both mean unknown.
    payload = object_value(
        value,
        "observation map",
        {"rows", "glyph_rows", "color_rows", "special_rows"},
        optional={"pet_rows"},
    )
    rows = tuple(
        string_value(row, "map row") for row in array_value(payload["rows"], "map rows")
    )
    glyph_rows = tuple(
        tuple(
            integer_value(glyph, "map glyph", minimum=0)
            for glyph in array_value(row, "map glyph row")
        )
        for row in array_value(payload["glyph_rows"], "map glyph_rows")
    )
    pet_rows = payload.get("pet_rows")
    return MapView(
        rows=rows,
        glyph_rows=glyph_rows,
        color_rows=_byte_rows(payload["color_rows"], "map color_rows"),
        special_rows=_byte_rows(payload["special_rows"], "map special_rows"),
        pet_rows=None if pet_rows is None else _byte_rows(pet_rows, "map pet_rows"),
    )


def _byte_rows(value: object, name: str) -> tuple[bytes, ...]:
    rows = []
    for item in array_value(value, name):
        text = string_value(item, f"{name} row")
        try:
            rows.append(bytes.fromhex(text))
        except ValueError as error:
            raise ContractError(f"{name} row must be hexadecimal bytes") from error
    return tuple(rows)


def _map_cell_change_from_json(value: object) -> MapCellChange:
    payload = object_value(
        value,
        "map cell change",
        {"x", "y", "character", "glyph", "color", "special"},
        optional={"pet"},
    )
    pet = payload.get("pet")
    return MapCellChange(
        x=integer_value(payload["x"], "changed cell x", minimum=0),
        y=integer_value(payload["y"], "changed cell y", minimum=0),
        character=string_value(
            payload["character"], "changed cell character", minimum=1, maximum=1
        ),
        glyph=integer_value(payload["glyph"], "changed cell glyph", minimum=0),
        color=integer_value(
            payload["color"], "changed cell color", minimum=0, maximum=255
        ),
        special=integer_value(
            payload["special"], "changed cell special", minimum=0, maximum=255
        ),
        pet=None if pet is None else boolean_value(pet, "changed cell pet"),
    )


def _player_stats_from_json(value: object) -> PlayerStats:
    payload = object_value(value, "player stats", _PLAYER_FIELDS)
    conditions = tuple(
        string_value(item, "player condition", minimum=1, maximum=80)
        for item in array_value(payload["conditions"], "player conditions")
    )
    if len(conditions) != len(set(conditions)):
        raise ContractError("player conditions must be unique")
    values = {
        field: integer_value(payload[field], f"player {field}")
        for field in _PLAYER_FIELDS
        if field != "conditions"
    }
    return PlayerStats(**values, conditions=conditions)


def _prompt_state_from_json(value: object) -> PromptState:
    payload = object_value(
        value,
        "prompt state",
        {"single_character_choice", "text_input", "wait_for_space"},
    )
    return PromptState(
        single_character_choice=boolean_value(
            payload["single_character_choice"], "single_character_choice"
        ),
        text_input=boolean_value(payload["text_input"], "text_input"),
        wait_for_space=boolean_value(payload["wait_for_space"], "wait_for_space"),
    )


def _inventory_item_from_json(value: object) -> InventoryItem:
    payload = object_value(
        value,
        "inventory item",
        {"letter", "description", "glyph", "object_class"},
        {"buc"},
    )
    return InventoryItem(
        letter=string_value(
            payload["letter"], "inventory letter", minimum=1, maximum=1
        ),
        description=string_value(
            payload["description"], "inventory description", maximum=4096
        ),
        glyph=integer_value(payload["glyph"], "inventory glyph", minimum=0),
        object_class=integer_value(
            payload["object_class"], "inventory object_class", minimum=0
        ),
        buc=enum_value(payload.get("buc", "unknown"), "inventory buc", BucStatus),
    )


def _cell_descriptions(
    observation: NleObservation, player: PlayerStats
) -> tuple[CellDescription, ...] | None:
    descriptions = observation.screen_descriptions
    if descriptions is None:
        return None
    # Decode only monsters, visible altar terrain and the hero's square.
    # The hero glyph hides terrain; ordinary look-here text can identify it.
    cells = []
    for y, row in enumerate(observation.glyphs):
        for x, value in enumerate(row):
            glyph = int(value)
            if (
                (x, y) == (player.x, player.y)
                or nethack.glyph_is_monster(glyph)
                or (nethack.glyph_is_cmap(glyph) and nethack.glyph_to_cmap(glyph) == 27)
            ):
                text = _decode_c_string(descriptions[y, x])
                if text:
                    cells.append(CellDescription(x, y, text))
    match = re.search(
        r"There is an? (?:high )?altar to [^\n]+ \((lawful|neutral|chaotic|unaligned)\) here\.",
        _decode_c_string(observation.message),
    )
    if match is not None and "hallucinating" not in player.conditions:
        cells = [cell for cell in cells if (cell.x, cell.y) != (player.x, player.y)]
        cells.append(CellDescription(player.x, player.y, f"{match.group(1)} altar"))
    return tuple(cells)


class ObservationProjector:
    """Copies compact public state before NLE reuses its observation buffers."""

    def __init__(self) -> None:
        self._previous_map: MapView | None = None

    def reset(self) -> None:
        self._previous_map = None

    def project(
        self, observation: NleObservation, *, step_index: int
    ) -> ProjectedObservation:
        player = self._player_stats(observation)
        map_view = MapView(
            rows=tuple(
                _display_row(
                    row,
                    glyphs,
                    row_index=y,
                    player_x=player.x,
                    player_y=player.y,
                )
                for y, (row, glyphs) in enumerate(
                    zip(observation.chars, observation.glyphs, strict=True)
                )
            ),
            glyph_rows=tuple(
                tuple(int(glyph) for glyph in row) for row in observation.glyphs
            ),
            color_rows=tuple(bytes(row) for row in observation.colors),
            special_rows=tuple(bytes(row) for row in observation.specials),
            pet_rows=tuple(_pet_row(row) for row in observation.glyphs),
        )
        changed_cells = self._changed_cells(map_view)
        self._previous_map = map_view
        return ProjectedObservation(
            step_index=step_index,
            map=map_view,
            changed_cells=changed_cells,
            player=player,
            message=_decode_c_string(observation.message),
            prompt=PromptState(
                single_character_choice=bool(observation.misc[0]),
                text_input=bool(observation.misc[1]),
                wait_for_space=bool(observation.misc[2]),
            ),
            inventory=self._inventory(observation),
            pickup_menu=pickup_menu_from_tty(observation.tty_chars),
            look_stair=stair_here_from_tty(observation.tty_chars),
            cell_descriptions=_cell_descriptions(observation, player),
        )

    def _changed_cells(self, current: MapView) -> tuple[MapCellChange, ...]:
        previous = self._previous_map
        if previous is None:
            return ()
        # Projected maps always carry pet evidence; only stored ones may not.
        assert current.pet_rows is not None and previous.pet_rows is not None
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
            pets,
            old_pets,
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
                current.pet_rows,
                previous.pet_rows,
                strict=True,
            )
        ):
            if (
                row == old_row
                and glyphs == old_glyphs
                and colors == old_colors
                and specials == old_specials
                and pets == old_pets
            ):
                continue
            changes.extend(
                MapCellChange(x, y, character, glyph, color, special, bool(pet))
                for x, (
                    character,
                    old_character,
                    glyph,
                    old_glyph,
                    color,
                    old_color,
                    special,
                    old_special,
                    pet,
                    old_pet,
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
                        pets,
                        old_pets,
                        strict=True,
                    )
                )
                if character != old_character
                or glyph != old_glyph
                or color != old_color
                or special != old_special
                or pet != old_pet
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
            decoded_description = _decode_c_string(description)
            items.append(
                InventoryItem(
                    letter=chr(letter_value),
                    description=decoded_description,
                    glyph=int(glyph),
                    object_class=int(object_class),
                    buc=_buc_status(decoded_description),
                )
            )
        return tuple(items)
