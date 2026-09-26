from __future__ import annotations

import json
import math
from collections.abc import Iterable
from enum import Enum


class ContractError(ValueError):
    """A persisted or transported value violates a domain contract."""


def object_value(value: object, name: str, fields: Iterable[str]) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ContractError(f"{name} must be an object")
    expected = set(fields)
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details = []
        if missing:
            details.append(f"missing {missing}")
        if extra:
            details.append(f"unexpected {extra}")
        raise ContractError(f"{name} fields are invalid: {', '.join(details)}")
    return value


def array_value(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise ContractError(f"{name} must be an array")
    return value


def string_value(
    value: object,
    name: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
    strip: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{name} must be a string")
    result = value.strip() if strip else value
    if len(result) < minimum or (maximum is not None and len(result) > maximum):
        upper = f" and {maximum}" if maximum is not None else ""
        raise ContractError(f"{name} length must be between {minimum}{upper}")
    return result


def integer_value(
    value: object,
    name: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise ContractError(f"{name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ContractError(f"{name} must be at most {maximum}")
    return value


def number_value(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ContractError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ContractError(f"{name} must be finite")
    return result


def boolean_value(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError(f"{name} must be a boolean")
    return value


def enum_value[EnumT: Enum](value: object, name: str, enum_type: type[EnumT]) -> EnumT:
    text = string_value(value, name)
    try:
        return enum_type(text)
    except ValueError as error:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise ContractError(f"{name} must be one of {choices}") from error


def optional_enum_value[EnumT: Enum](
    value: object, name: str, enum_type: type[EnumT]
) -> EnumT | None:
    return None if value is None else enum_value(value, name, enum_type)


def load_json_object(text: str, name: str) -> dict[str, object]:
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as error:
        raise ContractError(f"{name} is not valid JSON: {error.msg}") from error
    return object_value(value, name, value.keys() if isinstance(value, dict) else ())


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"JSON contains duplicate object key {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ContractError(f"JSON contains non-finite number {value}")
