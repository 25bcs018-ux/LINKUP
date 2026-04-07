"""Convert masked integer payloads into reversible symbol strings."""

from __future__ import annotations

import json
from pathlib import Path


PLACEVALUE_FILE = Path(__file__).with_name("placevalue.json")
NEGATIVE_MARKER = "~"


def _load_symbol_alphabet():
    with PLACEVALUE_FILE.open("r") as handle:
        raw_map = json.load(handle)

    ordered = []
    for key, symbol in sorted(raw_map.items(), key=lambda item: int(item[0])):
        if not isinstance(symbol, str) or len(symbol) != 1:
            raise ValueError(f"invalid symbol mapping for key {key}")
        ordered.append(symbol)

    if len(set(ordered)) != len(ordered):
        raise ValueError("placevalue symbols must be unique")
    if NEGATIVE_MARKER in ordered:
        raise ValueError("negative marker conflicts with symbol alphabet")

    return tuple(ordered)


SYMBOL_ALPHABET = _load_symbol_alphabet()
SYMBOL_TO_VALUE = {symbol: index for index, symbol in enumerate(SYMBOL_ALPHABET)}
SYMBOL_BASE = len(SYMBOL_ALPHABET)


def _normalize_integer_matrix(values, value_name):
    if not isinstance(values, list):
        raise TypeError(f"{value_name} must be a list of lists")

    normalized = []
    for line_index, line in enumerate(values):
        if not isinstance(line, list):
            raise TypeError(f"line {line_index} in {value_name} must be a list")

        normalized_line = []
        for token_index, token in enumerate(line):
            if isinstance(token, bool) or not isinstance(token, int):
                raise TypeError(
                    f"value at line {line_index}, index {token_index} must be an integer"
                )
            normalized_line.append(token)
        normalized.append(normalized_line)

    return normalized


def _normalize_symbol_matrix(values):
    if not isinstance(values, list):
        raise TypeError("symbolised_data must be a list of lists")

    normalized = []
    for line_index, line in enumerate(values):
        if not isinstance(line, list):
            raise TypeError(f"line {line_index} in symbolised_data must be a list")

        normalized_line = []
        for token_index, token in enumerate(line):
            if not isinstance(token, str) or not token:
                raise TypeError(
                    f"symbol at line {line_index}, index {token_index} must be a non-empty string"
                )
            normalized_line.append(token)
        normalized.append(normalized_line)

    return normalized


def _encode_integer(value):
    if value == 0:
        return SYMBOL_ALPHABET[0]

    number = abs(value)
    digits = []
    while number > 0:
        number, remainder = divmod(number, SYMBOL_BASE)
        digits.append(SYMBOL_ALPHABET[remainder])

    encoded = "".join(reversed(digits))
    if value < 0:
        return NEGATIVE_MARKER + encoded
    return encoded


def _decode_integer(value):
    negative = value.startswith(NEGATIVE_MARKER)
    digits = value[1:] if negative else value
    if not digits:
        raise ValueError("invalid symbol string")

    decoded = 0
    for char in digits:
        if char not in SYMBOL_TO_VALUE:
            raise ValueError(f"unknown symbol {char!r}")
        decoded = (decoded * SYMBOL_BASE) + SYMBOL_TO_VALUE[char]

    if negative:
        return -decoded
    return decoded


def _encode_matrix(masked_data):
    normalized = _normalize_integer_matrix(masked_data, "masked_data")
    return [[_encode_integer(token) for token in line] for line in normalized]


def _decode_matrix(symbolised_data):
    normalized = _normalize_symbol_matrix(symbolised_data)
    return [[_decode_integer(token) for token in line] for line in normalized]


def symboliser(masked_data):
    """Convert masked integer data into a self-describing symbol payload."""

    if isinstance(masked_data, dict):
        payload = dict(masked_data)
        encoded = _encode_matrix(payload.get("masked_data"))
        payload.pop("masked_data", None)
        payload["symbol_strategy"] = f"placevalue-base{SYMBOL_BASE}"
        payload["symbolised_data"] = encoded
        return payload

    return {
        "symbol_strategy": f"placevalue-base{SYMBOL_BASE}",
        "symbolised_data": _encode_matrix(masked_data),
    }


def desymboliser(symbolised_payload):
    """Convert a symbol payload back into integer masked data."""

    if isinstance(symbolised_payload, dict):
        payload = dict(symbolised_payload)
        strategy = payload.get("symbol_strategy")
        expected_strategy = f"placevalue-base{SYMBOL_BASE}"
        if strategy != expected_strategy:
            raise ValueError("unknown symbol strategy")

        decoded = _decode_matrix(payload.get("symbolised_data"))
        payload.pop("symbolised_data", None)
        payload["masked_data"] = decoded

        metadata_keys = set(payload) - {"symbol_strategy", "masked_data"}
        if not metadata_keys:
            return decoded
        return payload

    return _decode_matrix(symbolised_payload)

