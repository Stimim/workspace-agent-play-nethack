"""Read-only NLE 1.3.0 ground truth. Diagnosis only; never import in policy code."""

from __future__ import annotations

import _ctypes
import ctypes as C
import os
import platform
from pathlib import Path

import nle
from nle import nethack

from nethack_agent.environment import EnvironmentState, NleEnvironment, NleObservation

TERRAIN = [
    "STONE",
    "VWALL",
    "HWALL",
    "TLCORNER",
    "TRCORNER",
    "BLCORNER",
    "BRCORNER",
    "CROSSWALL",
    "TUWALL",
    "TDWALL",
    "TLWALL",
    "TRWALL",
    "DBWALL",
    "TREE",
    "SDOOR",
    "SCORR",
    "POOL",
    "MOAT",
    "WATER",
    "DRAWBRIDGE_UP",
    "LAVAPOOL",
    "IRONBARS",
    "DOOR",
    "CORR",
    "ROOM",
    "STAIRS",
    "LADDER",
    "FOUNTAIN",
    "THRONE",
    "SINK",
    "GRAVE",
    "ALTAR",
    "ICE",
    "DRAWBRIDGE_DOWN",
    "AIR",
    "CLOUD",
]


class ValidationError(RuntimeError):
    """The native layout or instance does not agree with public evidence."""


class Rm(C.Structure):
    # v1.3.0 include/rm.h; GCC packs the unsigned bitfields into bytes 6/7.
    _fields_ = [
        ("glyph", C.c_int),
        ("typ", C.c_int8),
        ("seenv", C.c_uint8),
        ("flags", C.c_uint8),
        ("room", C.c_uint8),
    ]


class Stairway(C.Structure):
    _fields_ = [(name, C.c_int8) for name in ("x", "y", "dnum", "dlevel", "up")]


def door_state(typ: int, flags: int) -> str | None:
    """SDOOR low three bits are wall mode, NOT door state (detect.c)."""
    mask = flags & 31
    if typ == 14:
        mask &= ~7
        return "LOCKED" if mask & 8 else "CLOSED"
    if typ != 22:
        return None
    if mask & 8:
        return "LOCKED"
    if mask & 4:
        return "CLOSED"
    if mask & 2:
        return "OPEN"
    if mask & 1:
        return "BROKEN"
    return "DOORWAY"


class NativeTruth:
    """An extra RTLD_NOLOAD handle owned until close, before the env closes.

    Use nested contexts: ``with NleEnvironment(...) as env`` then
    ``with NativeTruth(env, env.reset()) as truth``. Only the current level
    exists in these globals. Terminal snapshots omit ALL heap collections.
    """

    def __init__(self, env: NleEnvironment, observation: NleObservation) -> None:
        if nle.__version__ != "1.3.0" or platform.machine() != "x86_64":
            raise ValidationError("requires Linux x86_64 NLE 1.3.0 ABI")
        if env.state is not EnvironmentState.RUNNING:
            raise ValidationError("attach requires a live, reset environment")
        self.env = env
        self.library = None
        # NLE's dlpath identifies THIS instance, including simultaneous envs.
        path = env._raw_environment.nethack.dlpath
        inode = os.stat(path).st_ino
        mappings = [
            line.split()
            for line in Path("/proc/self/maps").read_text().splitlines()
            if "/memfd:nle.so" in line
        ]
        if not any(int(parts[4]) == inode for parts in mappings):
            raise ValidationError("instance memfd inode absent from /proc/self/maps")
        self.library = C.CDLL(path, mode=os.RTLD_NOLOAD | os.RTLD_NOW)
        self.inode = inode
        try:
            self.validate(observation)
            # sp_levchn is heap allocated and freed on death: copy now.
            self._special_levels = self._special_table()
        except BaseException:
            self.close()
            raise

    def __enter__(self) -> NativeTruth:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self.library is not None:
            _ctypes.dlclose(self.library._handle)
            self.library = None

    def _address(self, symbol: str) -> int:
        if self.library is None or self.env.state is EnvironmentState.CLOSED:
            raise ValidationError("reader/environment closed")
        return C.addressof(C.c_char.in_dll(self.library, symbol))

    def _bytes(self, symbol: str, size: int, offset: int = 0) -> bytes:
        return C.string_at(self._address(symbol) + offset, size)

    @staticmethod
    def _heap(address: int, size: int) -> bytes:
        # pread returns an error instead of segfaulting for unmapped addresses.
        # It does NOT make freed-but-mapped memory safe; lifecycle guard is vital.
        with open("/proc/self/mem", "rb", buffering=0) as memory:
            data = os.pread(memory.fileno(), size, address)
        if len(data) != size:
            raise ValidationError("short native heap read")
        return data

    def _pointer(self, symbol: str, offset: int = 0) -> int:
        return int.from_bytes(self._bytes(symbol, 8, offset), "little")

    def _hero(self) -> dict:
        data = self._bytes("u", 12)
        return {"x": data[0] - 1, "y": data[1], "dnum": data[10], "dlevel": data[11]}

    def _stairs(self) -> dict:
        result = {}
        hero = self._hero()
        for name in ("dnstair", "upstair", "dnladder", "upladder", "sstairs"):
            stair = Stairway.from_buffer_copy(self._bytes(name, 5))
            up = bool(stair.up) if name == "sstairs" else name.startswith("up")
            destination = (
                [stair.dnum, stair.dlevel]
                if name == "sstairs"
                else [hero["dnum"], hero["dlevel"] + (-1 if up else 1)]
            )
            result[name] = (
                {"x": stair.x - 1, "y": stair.y, "destination": destination, "up": up}
                if stair.x
                else None
            )
        return result

    def _map(self) -> list[list[dict]]:
        raw = self._bytes("level", 13440)
        return [
            [
                self._cell(Rm.from_buffer_copy(raw, ((x + 1) * 21 + y) * 8))
                for x in range(79)
            ]
            for y in range(21)
        ]

    @staticmethod
    def _cell(cell: Rm) -> dict:
        if not 0 <= cell.typ < len(TERRAIN):
            raise ValidationError(f"invalid rm typ {cell.typ}")
        return {
            "typ": cell.typ,
            "terrain": TERRAIN[cell.typ],
            "flags": cell.flags & 31,
            "seenv": cell.seenv,
            "roomno": cell.room & 63,
            "door_state": door_state(cell.typ, cell.flags),
        }

    def validate(self, observation: NleObservation) -> dict:
        if (
            C.sizeof(Rm) != 8
            or Rm.typ.offset != 4
            or Rm.seenv.offset != 5
            or Rm.flags.offset != 6
            or Rm.room.offset != 7
        ):
            raise ValidationError("rm size/offset mismatch")
        if C.sizeof(Stairway) != 5:
            raise ValidationError("stairway size mismatch")
        hero = self._hero()
        stats = observation.blstats
        expected = {
            "x": int(stats[0]),
            "y": int(stats[1]),
            "dnum": int(stats[23]),
            "dlevel": int(stats[24]),
        }
        if hero != expected:
            raise ValidationError(f"native hero {hero} != public {expected}")
        grid = self._map()
        if grid[hero["y"]][hero["x"]]["typ"] not in range(22, 36):
            raise ValidationError("hero rm offset does not identify accessible terrain")
        stairs = self._stairs()
        checked = 0
        for name, stair in stairs.items():
            if stair is not None:
                typ = 26 if "ladder" in name else 25
                if grid[stair["y"]][stair["x"]]["typ"] != typ:
                    raise ValidationError(f"rm stride/typ disagrees with {name}")
                checked += 1
        visible = 0
        # Public glyph checks validate stride AND typ against independent data.
        for y, row in enumerate(observation.glyphs):
            for native_x, glyph in enumerate(row, 1):
                if not nethack.glyph_is_cmap(int(glyph)):
                    continue
                cmap = nethack.glyph_to_cmap(int(glyph))
                typ = grid[y][native_x - 1]["typ"]
                if cmap in (23, 24, 25, 26):
                    name = {
                        23: "upstair",
                        24: "dnstair",
                        25: "upladder",
                        26: "dnladder",
                    }[cmap]
                    positions = [s for s in (stairs[name], stairs["sstairs"]) if s]
                    if not any(
                        s["x"] == native_x - 1 and s["y"] == y for s in positions
                    ):
                        raise ValidationError(
                            f"visible {name} disagrees with native stairs"
                        )
                    visible += 1
                # wall_angle() renders junctions according to seenv; the glyph
                # need not have the same subtype as native typ. SDOOR is a wall.
                if 1 <= cmap <= 11 and not (1 <= typ <= 12 or typ == 14):
                    raise ValidationError(
                        f"visible wall ({native_x - 1},{y}) cmap={cmap} typ={typ} "
                        "disagrees with rm size/typ offset"
                    )
                state = grid[y][native_x - 1]["door_state"]
                if typ == 22 and cmap in (13, 14, 15, 16):
                    expected_states = (
                        ("OPEN",) if cmap in (13, 14) else ("CLOSED", "LOCKED")
                    )
                    if state not in expected_states:
                        raise ValidationError(
                            "visible door disagrees with rm flags offset"
                        )
        return {
            "rm_size": 8,
            "typ_offset": 4,
            "seenv_offset": 5,
            "flags_offset": 6,
            "u_uz_offset": 10,
            "native_stairs_checked": checked,
            "visible_stairs_checked": visible,
        }

    def _special_table(self) -> dict:
        result = {}
        pointer = self._pointer("sp_levchn")
        visited = set()
        while pointer:
            if pointer in visited or len(visited) > 128:
                raise ValidationError("invalid special-level chain")
            visited.add(pointer)
            data = self._heap(pointer, 32)
            result[(data[8], data[9])] = data[10:25].split(b"\0")[0].decode()
            pointer = int.from_bytes(data[:8], "little")
        return result

    def _rooms(self) -> list[dict]:
        result = []
        for symbol, count_symbol, base in (
            ("rooms", "nroom", 0),
            ("subrooms", "nsubroom", 41),
        ):
            count = int.from_bytes(self._bytes(count_symbol, 4), "little", signed=True)
            if not 0 <= count <= 40:
                raise ValidationError(f"invalid {count_symbol}")
            # subrooms points inside the static rooms[] allocation, not heap.
            raw = self._bytes("rooms", 216 * count, 216 * base)
            for i in range(count):
                room = raw[i * 216 : (i + 1) * 216]
                result.append(
                    {
                        "index": base + i,
                        "subroom": symbol == "subrooms",
                        "bounds": [room[0] - 1, room[1] - 1, room[2], room[3]],
                        "type": room[4],
                        "original_type": room[5],
                        "kind": "temple"
                        if room[4] == 10
                        else ("shop" if room[4] >= 14 else "ordinary_or_special"),
                    }
                )
        return result

    def _dynamic(self) -> dict:
        result = {"traps": [], "boulders": [], "peaceful_monsters": []}
        pointer = self._pointer("ftrap")
        visited = set()
        while pointer:
            if pointer in visited or len(visited) > 1000:
                raise ValidationError("invalid trap chain")
            visited.add(pointer)
            data = self._heap(pointer, 24)
            result["traps"].append(
                {
                    "x": data[8] - 1,
                    "y": data[9],
                    "typ": data[14] & 31,
                    "seen": bool(data[14] & 32),
                    "destination": [data[10], data[11]],
                }
            )
            pointer = int.from_bytes(data[:8], "little")
        pointer = self._pointer("level", 40320)  # level.objlist
        visited = set()
        boulder_type = next(
            i
            for i in range(nethack.NUM_OBJECTS)
            if nethack.objdescr.from_idx(i).oc_name == "boulder"
        )
        while pointer:
            if pointer in visited or len(visited) > 10000:
                raise ValidationError("invalid object chain")
            visited.add(pointer)
            data = self._heap(pointer, 32)
            if int.from_bytes(data[30:32], "little") == boulder_type:
                result["boulders"].append({"x": data[28] - 1, "y": data[29]})
            pointer = int.from_bytes(data[:8], "little")
        pointer = self._pointer("level", 40336)  # level.monlist
        visited = set()
        while pointer:
            if pointer in visited or len(visited) > 10000:
                raise ValidationError("invalid monster chain")
            visited.add(pointer)
            data = self._heap(pointer, 72)
            # Seven packed bitfield bytes begin at 60; mpeaceful = byte65 bit1.
            if data[65] & 2 and not data[53]:
                result["peaceful_monsters"].append(
                    {
                        "x": data[28] - 1,
                        "y": data[29],
                        "monster_index": int.from_bytes(
                            data[20:22], "little", signed=True
                        ),
                    }
                )
            pointer = int.from_bytes(data[:8], "little")
        return result

    def snapshot(self, observation: NleObservation) -> dict:
        terminal = self.env.state is EnvironmentState.TERMINAL
        hero = self._hero()
        # Terminal blstats can be zeroed: no fake live validation, no heap reads.
        validation = None if terminal else self.validate(observation)
        dnum = hero["dnum"]
        if not 0 <= dnum < 16:
            raise ValidationError("invalid dungeon number")
        dungeon = self._bytes("dungeons", 56, 56 * dnum)
        flags = self._bytes("level", 8, 40360)
        result = {
            "hero": hero,
            "terrain": self._map(),
            "stairs": self._stairs(),
            "dungeon_name": dungeon[:24].split(b"\0")[0].decode(),
            "special_level": self._special_levels.get((dnum, hero["dlevel"])),
            "level_flags": {
                "has_shop": bool(flags[2] & 1),
                "has_temple": bool(flags[2] & 128),
                "sokoban_rules": bool(flags[3] & 128),
            },
            "rooms": self._rooms(),
            "terminal": terminal,
            "validation": validation,
            "dynamic_status": "unavailable_post_terminal" if terminal else "live",
        }
        if not terminal:
            result.update(self._dynamic())
        result["special_variant_candidates"] = minetown_variants(result)
        return result


def minetown_variants(snapshot: dict) -> list[str]:
    """Source-derived structural candidates, NOT an exported filename.

    mkmaze.c keeps the selected filename on its stack. Temple dimensions
    and altar/fountain distances in dat/mines.des survive map flips.
    """
    if snapshot["special_level"] != "minetn":
        return []
    temples = [r for r in snapshot["rooms"] if r["original_type"] == 10]
    if not temples:
        return ["minetn-1"]  # Orcish Town's altar is in an ordinary region.
    candidates = []
    dimensions = {
        (4, 4): [2, 7],
        (3, 4): [3],
        (5, 4): [4],
        (5, 3): [5],
        (6, 3): [6],
    }
    for room in temples:
        lx, hx, ly, hy = room["bounds"]
        choices = dimensions.get((hx - lx + 1, hy - ly + 1), [])
        if choices == [2, 7]:
            grid = snapshot["terrain"]
            altars = [
                (x, y)
                for y in range(ly, hy + 1)
                for x in range(lx, hx + 1)
                if grid[y][x]["typ"] == 31
            ]
            fountains = [
                (x, y)
                for y, row in enumerate(grid)
                for x, cell in enumerate(row)
                if cell["typ"] == 27
            ]
            if len(altars) == 1 and len(fountains) == 2:
                ax, ay = altars[0]
                distances = sorted((x - ax) ** 2 + (y - ay) ** 2 for x, y in fountains)
                if distances == [20, 65]:
                    choices = [2]
                elif distances == [196, 261]:
                    choices = [7]
        candidates.extend(f"minetn-{choice}" for choice in choices)
    return sorted(set(candidates))
