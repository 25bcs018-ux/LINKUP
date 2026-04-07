import json
from pathlib import Path


TOKEN_FILE = Path(__file__).with_name("token.json")
DYNAMIC_TOKEN_BASE = 2_000_000


def _load_token_map():
    try:
        with TOKEN_FILE.open("r") as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}

    if not isinstance(data, dict):
        raise ValueError("token.json must contain a JSON object")
    return data


def _inverse_token_map(token_map):
    inverse = {}
    for char, token in token_map.items():
        if isinstance(char, str) and len(char) == 1 and isinstance(token, int):
            inverse[token] = char
    return inverse


def tokenize_text(text):
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    token_map = _load_token_map()
    tokens = []
    for char in text:
        if char in token_map:
            tokens.append(token_map[char])
        else:
            tokens.append(DYNAMIC_TOKEN_BASE + ord(char))
    return tokens


def detokenize_tokens(tokens):
    if not isinstance(tokens, list):
        raise TypeError("tokens must be a list of integers")

    inverse_map = _inverse_token_map(_load_token_map())
    chars = []
    for index, token in enumerate(tokens):
        if isinstance(token, bool) or not isinstance(token, int):
            raise TypeError(f"token at index {index} must be an integer")
        if token in inverse_map:
            chars.append(inverse_map[token])
            continue
        if token >= DYNAMIC_TOKEN_BASE:
            chars.append(chr(token - DYNAMIC_TOKEN_BASE))
            continue
        raise ValueError(f"unknown token {token}")

    return "".join(chars)


def untokenizer(token_lines):
    if not isinstance(token_lines, list):
        raise TypeError("token_lines must be a list")

    return [detokenize_tokens(tokens) for tokens in token_lines]

def tokenizer(chat_data):
    if not isinstance(chat_data, list):
        raise TypeError("chat_data must be a list")

    token_lines = []
    for line_index, line in enumerate(chat_data):
        if isinstance(line, str):
            text = line
        elif isinstance(line, list):
            if not all(isinstance(word, str) for word in line):
                raise TypeError(f"line {line_index} must contain only strings")
            text = " ".join(line)
        else:
            raise TypeError(f"line {line_index} must be a string or list of strings")

        token_lines.append(tokenize_text(text))

    return token_lines

# Example usage:
# chat_data = [["Hello", "world"], ["Testing"]]
# print(tokenizer(chat_data))
