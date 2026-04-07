"""Custom reversible text pipeline built from the encryption package helpers."""

from __future__ import annotations

import json

from encryption.masking import dmask, unmask
from encryption.symbolisation import desymboliser, symboliser
from encryption.tokenization import detokenize_tokens, tokenize_text


CUSTOM_PIPELINE_PREFIX = "linkup-custom-v1|"
TRANSPORT_PIPELINE_PREFIX = "linkup-transport-v1|"


def _text_to_codepoint_tokens(text):
    return [ord(char) for char in text]


def _codepoint_tokens_to_text(tokens):
    return "".join(chr(token) for token in tokens)


def custom_encode_text(text, mask_seed=None, strategy_name=None):
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    token_line = tokenize_text(text)
    masked_payload = dmask([token_line], mask_seed=mask_seed, strategy_name=strategy_name)
    symbol_payload = symboliser(masked_payload)
    return CUSTOM_PIPELINE_PREFIX + json.dumps(symbol_payload, separators=(",", ":"))


def custom_decode_text(payload):
    if not isinstance(payload, str):
        raise TypeError("payload must be a string")
    if not payload.startswith(CUSTOM_PIPELINE_PREFIX):
        return payload

    symbol_payload = json.loads(payload[len(CUSTOM_PIPELINE_PREFIX) :])
    masked_payload = desymboliser(symbol_payload)
    token_lines = unmask(masked_payload)

    if len(token_lines) != 1:
        raise ValueError("custom payload must contain exactly one token line")

    return detokenize_tokens(token_lines[0])


def transport_encode_text(text, mask_seed=None, strategy_name=None):
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    masked_payload = dmask([
        _text_to_codepoint_tokens(text)
    ], mask_seed=mask_seed, strategy_name=strategy_name)
    symbol_payload = symboliser(masked_payload)
    return TRANSPORT_PIPELINE_PREFIX + json.dumps(symbol_payload, separators=(",", ":"))


def transport_decode_text(payload):
    if not isinstance(payload, str):
        raise TypeError("payload must be a string")
    if not payload.startswith(TRANSPORT_PIPELINE_PREFIX):
        return payload

    symbol_payload = json.loads(payload[len(TRANSPORT_PIPELINE_PREFIX) :])
    masked_payload = desymboliser(symbol_payload)
    token_lines = unmask(masked_payload)
    if len(token_lines) != 1:
        raise ValueError("transport payload must contain exactly one token line")

    return _codepoint_tokens_to_text(token_lines[0])