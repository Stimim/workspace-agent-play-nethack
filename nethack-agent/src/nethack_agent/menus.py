"""Bounded pickup-menu evidence from NLE's public terminal characters."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Self

from nethack_agent.contracts import (
    array_value,
    boolean_value,
    integer_value,
    object_value,
    string_value,
)


@dataclass(frozen=True, slots=True)
class PickupChoice:
    letter: str
    description: str
    selected: bool

    def __post_init__(self) -> None:
        if re.fullmatch(r"[A-Za-z]", self.letter) is None:
            raise ValueError("pickup choice requires one inventory letter")
        string_value(self.description, "pickup description", minimum=1, maximum=160)
        boolean_value(self.selected, "pickup selected")


@dataclass(frozen=True, slots=True)
class PickupMenu:
    choices: tuple[PickupChoice, ...]
    page: int = 1
    pages: int = 1

    def __post_init__(self) -> None:
        integer_value(self.pages, "pickup pages", minimum=1, maximum=100)
        integer_value(self.page, "pickup page", minimum=1, maximum=self.pages)
        if len(self.choices) > 52 or len({item.letter for item in self.choices}) != len(
            self.choices
        ):
            raise ValueError("pickup menu choices must have unique letters")

    def to_json(self) -> dict[str, object]:
        return {
            "choices": [asdict(item) for item in self.choices],
            "page": self.page,
            "pages": self.pages,
        }

    @classmethod
    def from_json(cls, value: object) -> Self:
        payload = object_value(value, "pickup menu", {"choices", "page", "pages"})
        choices = []
        for value in array_value(payload["choices"], "pickup choices"):
            item = object_value(
                value, "pickup choice", {"letter", "description", "selected"}
            )
            choices.append(
                PickupChoice(
                    string_value(item["letter"], "pickup letter", minimum=1, maximum=1),
                    string_value(
                        item["description"],
                        "pickup description",
                        minimum=1,
                        maximum=160,
                    ),
                    boolean_value(item["selected"], "pickup selected"),
                )
            )
        return cls(
            tuple(choices),
            integer_value(payload["page"], "pickup page", minimum=1),
            integer_value(payload["pages"], "pickup pages", minimum=1),
        )


def pickup_menu_from_tty(rows: Iterable[Iterable[int]]) -> PickupMenu | None:
    choices = []
    column = None
    for raw_row in rows:
        row = bytes(raw_row).decode("latin1").rstrip()
        if column is None:
            if row.strip() == "Pick up what?":
                column = len(row) - len(row.lstrip())
            continue
        text = row[column:].strip()
        if text == "(end)":
            return PickupMenu(tuple(choices))
        footer = re.fullmatch(r"\((\d+) of (\d+)\)", text)
        if footer is not None:
            return PickupMenu(tuple(choices), int(footer[1]), int(footer[2]))
        entry = re.fullmatch(r"([A-Za-z]) ([-+]) (.+)", text)
        if entry is not None:
            choices.append(PickupChoice(entry[1], entry[3], entry[2] == "+"))
    return None
