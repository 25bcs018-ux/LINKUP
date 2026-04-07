"""Custom (project) encryption layer.

This module encrypts chat message content before storing it in the database.

The default scheme here is `v3:` using AES-GCM from the `cryptography`
package, with plaintext first passed through the custom reversible pipeline
from the `encryption/` package.

Format:
- `v3:<base64url(nonce || ciphertext || tag)>`
    - nonce: 12 bytes
    - tag:   16 bytes (AES-GCM authentication tag)

Legacy compatibility:
- `v2:<base64url(nonce || ciphertext || tag)>`
    - nonce: 16 bytes
    - tag:   16 bytes (custom MAC)

Compatibility:
- Plaintext messages (no prefix) are treated as legacy and returned as-is.
- `v1:` tokens are still decryptable (legacy only) to avoid breaking existing DB
    rows created before `v2:` existed.

Important security note:
`v3:` is suitable for real application use if you manage keys correctly.
The legacy `v2:` custom scheme is kept only so existing stored rows remain
decryptable.

Key management:
- Prefer setting CHAT_ENC_KEY as base64url-encoded 32 bytes.
- If CHAT_ENC_KEY is missing, we derive a 32-byte key from SECRET_KEY using a
    custom mixing function (stdlib-only).
"""

from __future__ import annotations

import base64
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from encryption.pipeline import custom_decode_text, custom_encode_text


V1_PREFIX = "v1:"
V2_PREFIX = "v2:"
V3_PREFIX = "v3:"
NONCE_LEN = 16
V3_NONCE_LEN = 12
V1_TAG_LEN = 32  # legacy HMAC-SHA256
V2_TAG_LEN = 16  # custom MAC
MASTER_KEY_LEN = 32
V3_AAD = b"linkup:aesgcm:v3"


class CryptoError(Exception):
    """Raised when encrypted payload cannot be decrypted/verified."""


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    s = data.strip().encode("ascii")
    s += b"=" * ((4 - (len(s) % 4)) % 4)
    return base64.urlsafe_b64decode(s)


def generate_key_b64url(nbytes: int = MASTER_KEY_LEN) -> str:
    """Generate a random key and return it as base64url (no padding)."""
    return _b64url_encode(secrets.token_bytes(nbytes))


def _fallback_key_file() -> Path:
    return Path(__file__).resolve().parent / "instance" / ".demo_enc_key"


def _load_persisted_master_key() -> bytes | None:
    path = _fallback_key_file()
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    if not raw:
        return None

    try:
        key = _b64url_decode(raw)
    except Exception:
        return None

    if len(key) != MASTER_KEY_LEN:
        return None
    return key


def _load_master_key() -> bytes:
    """Load a 32-byte master key.

    Priority:
    1) CHAT_ENC_KEY (base64url or standard base64)
    2) Derive from SECRET_KEY (custom legacy-compatible KDF)
    """
    raw = os.environ.get("CHAT_ENC_KEY", "").strip()
    if raw:
        try:
            key = _b64url_decode(raw)
        except Exception as exc:  # noqa: BLE001
            raise CryptoError("CHAT_ENC_KEY is not valid base64/base64url") from exc
        if len(key) != MASTER_KEY_LEN:
            raise CryptoError(f"CHAT_ENC_KEY must decode to {MASTER_KEY_LEN} bytes")
        return key

    persisted = _load_persisted_master_key()
    if persisted is not None:
        return persisted

    secret = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
    return _kdf_from_secret(secret)


@dataclass(frozen=True)
class _Keys:
    enc: bytes
    auth: bytes


def _derive_subkeys(master: bytes) -> _Keys:
    # v2 uses stdlib-only derivation and doesn't need these.
    # Kept for v1 legacy decryption.
    import hashlib
    import hmac

    enc = hmac.new(master, b"linkup:enc", hashlib.sha256).digest()
    auth = hmac.new(master, b"linkup:auth", hashlib.sha256).digest()
    return _Keys(enc=enc, auth=auth)


def _keystream(enc_key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        ctr = counter.to_bytes(4, "big")
        import hashlib
        import hmac

        block = hmac.new(enc_key, nonce + ctr, hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


MASK64 = (1 << 64) - 1


def _rotl64(x: int, r: int) -> int:
    x &= MASK64
    return ((x << r) & MASK64) | (x >> (64 - r))


def _splitmix64_next(state: int) -> tuple[int, int]:
    """SplitMix64: returns (value, new_state)."""
    state = (state + 0x9E3779B97F4A7C15) & MASK64
    z = state
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9 & MASK64
    z = (z ^ (z >> 27)) * 0x94D049BB133111EB & MASK64
    z = z ^ (z >> 31)
    return z & MASK64, state


def _xorshift128plus_next(s0: int, s1: int) -> tuple[int, int, int]:
    """xorshift128+ PRNG step: returns (value, new_s0, new_s1)."""
    x = s0 & MASK64
    y = s1 & MASK64
    s0_new = y
    x ^= (x << 23) & MASK64
    x ^= (x >> 17) & MASK64
    x ^= y
    x ^= (y >> 26) & MASK64
    s1_new = x & MASK64
    value = (s0_new + s1_new) & MASK64
    return value, s0_new, s1_new


def _kdf_from_secret(secret: str) -> bytes:
    """Custom KDF (stdlib-only).

    Mixes SECRET_KEY bytes into a SplitMix64 stream to yield 32 bytes.
    """
    data = ("linkup:kdf:v2|" + (secret or "")).encode("utf-8")
    st = 0x243F6A8885A308D3
    for i, b in enumerate(data):
        st ^= (b + 0x9E + (i * 0x27)) & MASK64
        val, st = _splitmix64_next(st)
        st ^= _rotl64(val, (i % 63) + 1)

    out = bytearray()
    while len(out) < MASTER_KEY_LEN:
        val, st = _splitmix64_next(st)
        out.extend(val.to_bytes(8, "big"))
    return bytes(out[:MASTER_KEY_LEN])


def _derive_v2_state(master: bytes, nonce: bytes) -> tuple[int, int]:
    # Build two 64-bit seeds from (master || nonce) using SplitMix.
    if len(master) != MASTER_KEY_LEN:
        raise CryptoError("invalid master key length")
    if len(nonce) != NONCE_LEN:
        raise CryptoError("invalid nonce length")

    st = 0x13198A2E03707344
    for b in master + nonce + b"linkup:stream:v2":
        st ^= (b + 0xA5) & MASK64
        val, st = _splitmix64_next(st)
        st ^= _rotl64(val, 17)

    v0, st = _splitmix64_next(st)
    v1, st = _splitmix64_next(st)
    # Avoid all-zero state.
    if (v0 | v1) == 0:
        v1 = 0x9E3779B97F4A7C15
    return v0, v1


def _v2_keystream(master: bytes, nonce: bytes, length: int) -> bytes:
    s0, s1 = _derive_v2_state(master, nonce)
    out = bytearray()
    while len(out) < length:
        val, s0, s1 = _xorshift128plus_next(s0, s1)
        # add non-linearity via ARX mixing
        mixed = (val + _rotl64(val, 29) + (s0 ^ _rotl64(s1, 37))) & MASK64
        out.extend(mixed.to_bytes(8, "big"))
    return bytes(out[:length])


def _v2_mac(master: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
    """Custom 128-bit tag (not a standard MAC)."""
    s0, s1 = _derive_v2_state(master, nonce)
    a = (s0 ^ 0xA5A5A5A5A5A5A5A5) & MASK64
    b = (s1 ^ 0x0123456789ABCDEF) & MASK64

    for i, byte in enumerate(ciphertext):
        a = (a + byte + ((i + 1) * 0x9E37)) & MASK64
        a ^= _rotl64(a, 13)
        b = (b ^ a) & MASK64
        b = (b * 0xD6E8FEB86659FD93) & MASK64
        b ^= _rotl64(b, 17)

    # finalize
    for _ in range(8):
        v, s0, s1 = _xorshift128plus_next(s0, s1)
        a ^= v
        a = (a * 0x94D049BB133111EB) & MASK64
        b ^= _rotl64(v, 23)
        b = (b * 0xBF58476D1CE4E5B9) & MASK64

    return a.to_bytes(8, "big") + b.to_bytes(8, "big")


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def _encrypt_v3(plaintext: bytes) -> str:
    master = _load_master_key()
    nonce = secrets.token_bytes(V3_NONCE_LEN)
    ciphertext = AESGCM(master).encrypt(nonce, bytes(plaintext), V3_AAD)
    return V3_PREFIX + _b64url_encode(nonce + ciphertext)


def _decrypt_v3(token: str) -> bytes:
    b64 = token[len(V3_PREFIX) :]
    try:
        blob = _b64url_decode(b64)
    except Exception as exc:  # noqa: BLE001
        raise CryptoError("invalid base64 payload") from exc

    if len(blob) < V3_NONCE_LEN + 16:
        raise CryptoError("payload too short")

    nonce = blob[:V3_NONCE_LEN]
    ciphertext = blob[V3_NONCE_LEN:]

    try:
        return AESGCM(_load_master_key()).decrypt(nonce, ciphertext, V3_AAD)
    except Exception as exc:  # noqa: BLE001
        raise CryptoError("authentication failed") from exc


def _encrypt_v2(plaintext: bytes) -> str:
    master = _load_master_key()
    nonce = secrets.token_bytes(NONCE_LEN)
    ks = _v2_keystream(master, nonce, len(plaintext))
    ciphertext = _xor(bytes(plaintext), ks)
    tag = _v2_mac(master, nonce, ciphertext)
    token = nonce + ciphertext + tag
    return V2_PREFIX + _b64url_encode(token)


def encrypt_bytes(plaintext: bytes) -> str:
    if not isinstance(plaintext, (bytes, bytearray)):
        raise TypeError("plaintext must be bytes")

    # Default: AES-GCM v3.
    return _encrypt_v3(bytes(plaintext))


def decrypt_bytes(token_or_plaintext: str) -> bytes:
    if not isinstance(token_or_plaintext, str):
        raise TypeError("token_or_plaintext must be str")

    s = token_or_plaintext
    if not (s.startswith(V3_PREFIX) or s.startswith(V2_PREFIX) or s.startswith(V1_PREFIX)):
        # legacy plaintext stored without encryption
        return s.encode("utf-8")

    if s.startswith(V3_PREFIX):
        return _decrypt_v3(s)

    if s.startswith(V2_PREFIX):
        b64 = s[len(V2_PREFIX) :]
        try:
            blob = _b64url_decode(b64)
        except Exception as exc:  # noqa: BLE001
            raise CryptoError("invalid base64 payload") from exc

        if len(blob) < NONCE_LEN + V2_TAG_LEN:
            raise CryptoError("payload too short")

        nonce = blob[:NONCE_LEN]
        tag = blob[-V2_TAG_LEN:]
        ciphertext = blob[NONCE_LEN:-V2_TAG_LEN]

        master = _load_master_key()
        expected = _v2_mac(master, nonce, ciphertext)
        # constant-time compare
        if not secrets.compare_digest(expected, tag):
            raise CryptoError("authentication failed")

        ks = _v2_keystream(master, nonce, len(ciphertext))
        return _xor(ciphertext, ks)

    # Legacy v1 decryption (kept to avoid breaking existing DB rows).
    b64 = s[len(V1_PREFIX) :]
    try:
        blob = _b64url_decode(b64)
    except Exception as exc:  # noqa: BLE001
        raise CryptoError("invalid base64 payload") from exc

    if len(blob) < NONCE_LEN + V1_TAG_LEN:
        raise CryptoError("payload too short")

    nonce = blob[:NONCE_LEN]
    tag = blob[-V1_TAG_LEN:]
    ciphertext = blob[NONCE_LEN:-V1_TAG_LEN]

    import hashlib
    import hmac

    master = _load_master_key()
    keys = _derive_subkeys(master)
    expected = hmac.new(keys.auth, nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, tag):
        raise CryptoError("authentication failed")

    ks = _keystream(keys.enc, nonce, len(ciphertext))
    return _xor(ciphertext, ks)


def encrypt_text(plaintext: str) -> str:
    if not isinstance(plaintext, str):
        raise TypeError("plaintext must be str")
    prepared = custom_encode_text(plaintext)
    return encrypt_bytes(prepared.encode("utf-8"))


def decrypt_text(token_or_plaintext: str) -> str:
    data = decrypt_bytes(token_or_plaintext)
    try:
        decoded = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CryptoError("decrypted bytes are not valid UTF-8") from exc

    try:
        return custom_decode_text(decoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CryptoError("custom pipeline payload is invalid") from exc


def _cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m crypto", description="LinkUp crypto helpers")
    sub = parser.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("gen-key", help="Generate a CHAT_ENC_KEY")
    g.add_argument("--bytes", type=int, default=MASTER_KEY_LEN)

    e = sub.add_parser("encrypt", help="Encrypt a message")
    e.add_argument("text")

    d = sub.add_parser("decrypt", help="Decrypt a token")
    d.add_argument("token")

    l = sub.add_parser("encrypt-legacy-v2", help="Encrypt using the legacy v2 format")
    l.add_argument("text")

    args = parser.parse_args()

    if args.cmd == "gen-key":
        print(generate_key_b64url(args.bytes))
        return 0

    if args.cmd == "encrypt":
        print(encrypt_text(args.text))
        return 0

    if args.cmd == "decrypt":
        print(decrypt_text(args.token))
        return 0

    if args.cmd == "encrypt-legacy-v2":
        print(_encrypt_v2(args.text.encode("utf-8")))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
