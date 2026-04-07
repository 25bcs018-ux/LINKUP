"""Helpers for reversible masking of tokenized chat data.

This module provides a lightweight obfuscation layer for integer token IDs.
It is not cryptography; it is only meant to mask token values in memory or in
temporary payloads.
"""

from __future__ import annotations

import secrets
from typing import Callable


MASK_MODULUS = 2**31 - 1


def _xor_transform(token, mask_value, salt):
    return token ^ mask_value ^ salt


def _xor_inverse(masked_token, mask_value, salt):
    return masked_token ^ mask_value ^ salt


def _shift_transform(token, mask_value, salt):
    return token + mask_value + salt


def _shift_inverse(masked_token, mask_value, salt):
    return masked_token - mask_value - salt


def _twist_transform(token, mask_value, salt):
    return (token ^ mask_value) + salt


def _twist_inverse(masked_token, mask_value, salt):
    return (masked_token - salt) ^ mask_value


MASKING_STRATEGIES: dict[str, tuple[Callable[[int, int, int], int], Callable[[int, int, int], int]]] = {
    "xor": (_xor_transform, _xor_inverse),
    "shift": (_shift_transform, _shift_inverse),
    "twist": (_twist_transform, _twist_inverse),
}


def _normalize_tokenized_data(tokenized_data):
    if not isinstance(tokenized_data, list):
        raise TypeError("tokenized_data must be a list of token lists")

    normalized = []
    for line_index, line in enumerate(tokenized_data):
        if not isinstance(line, list):
            raise TypeError(f"line {line_index} must be a list of integers")

        normalized_line = []
        for token_index, token in enumerate(line):
            if isinstance(token, bool) or not isinstance(token, int):
                raise TypeError(
                    f"token at line {line_index}, index {token_index} must be an integer"
                )
            normalized_line.append(token)
        normalized.append(normalized_line)

    return normalized


def _mask_value(mask_seed, line_index, token_index):
    value = mask_seed % MASK_MODULUS
    value = (value * 1103515245 + 12345 + ((line_index + 1) * 4099)) % MASK_MODULUS
    value = (value + ((token_index + 1) * 131071)) % MASK_MODULUS
    return value or 1


def _strategy_salt(mask_seed, line_index, token_index):
    salt = (mask_seed * 214013 + ((line_index + 1) * 2531011)) % MASK_MODULUS
    salt = (salt + ((token_index + 1) * 32719)) % MASK_MODULUS
    return salt or 1


def _choose_strategy(tokenized_data, mask_seed):
    normalized = _normalize_tokenized_data(tokenized_data)
    fingerprint = mask_seed % MASK_MODULUS

    for line_index, line in enumerate(normalized):
        for token_index, token in enumerate(line):
            fingerprint ^= ((line_index + 1) * 257) + ((token_index + 1) * 65537)
            fingerprint = (fingerprint + (token * 17) + len(line)) % MASK_MODULUS

    strategy_names = tuple(MASKING_STRATEGIES)
    return strategy_names[fingerprint % len(strategy_names)]


def identify_masking_strategy(masked_payload):
    if not isinstance(masked_payload, dict):
        raise TypeError("masked_payload must be a dictionary")

    strategy_name = masked_payload.get("strategy")
    if not isinstance(strategy_name, str) or strategy_name not in MASKING_STRATEGIES:
        raise ValueError("masked payload contains an unknown strategy")

    return strategy_name, MASKING_STRATEGIES[strategy_name]


def _apply_mask(tokenized_data, mask_seed, transform):
    normalized = _normalize_tokenized_data(tokenized_data)
    masked_data = []

    for line_index, line in enumerate(normalized):
        masked_line = []
        for token_index, token in enumerate(line):
            mask_value = _mask_value(mask_seed, line_index, token_index)
            salt = _strategy_salt(mask_seed, line_index, token_index)
            masked_line.append(transform(token, mask_value, salt))
        masked_data.append(masked_line)

    return masked_data


def dmask(tokenized_data, mask_seed=None, strategy_name=None):
    """Mask token IDs and return the masked payload with the seed used.

    The same seed can be passed to ``unmask`` to recover the original token IDs.
    """

    if mask_seed is None:
        mask_seed = secrets.randbelow(MASK_MODULUS - 1) + 1
    if isinstance(mask_seed, bool) or not isinstance(mask_seed, int):
        raise TypeError("mask_seed must be an integer")
    if mask_seed <= 0:
        raise ValueError("mask_seed must be greater than zero")

    if strategy_name is None:
        strategy_name = _choose_strategy(tokenized_data, mask_seed)
    elif strategy_name not in MASKING_STRATEGIES:
        raise ValueError("strategy_name must be one of the registered strategies")

    transform, _ = MASKING_STRATEGIES[strategy_name]

    return {
        "version": 1,
        "strategy": strategy_name,
        "mask_seed": mask_seed,
        "masked_data": _apply_mask(tokenized_data, mask_seed, transform),
    }


def unmask(masked_data, mask_seed=None, strategy_name=None):
    """Recover original token IDs from data returned by ``dmask``.

    When passed the full payload returned by ``dmask``, this fixed function reads
    the strategy metadata and dispatches to the right unmasking implementation.
    """

    if isinstance(masked_data, dict):
        payload = masked_data
        mask_seed = payload.get("mask_seed")
        masked_data = payload.get("masked_data")
        strategy_name, (_, inverse) = identify_masking_strategy(payload)
        return _apply_mask(masked_data, mask_seed, inverse)

    if isinstance(mask_seed, bool) or not isinstance(mask_seed, int):
        raise TypeError("mask_seed must be an integer")
    if mask_seed <= 0:
        raise ValueError("mask_seed must be greater than zero")

    if strategy_name is None:
        strategy_name = "xor"
    if strategy_name not in MASKING_STRATEGIES:
        raise ValueError("strategy_name must be one of the registered strategies")

    _, inverse = MASKING_STRATEGIES[strategy_name]
    return _apply_mask(masked_data, mask_seed, inverse)
