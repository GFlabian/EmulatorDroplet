import base64
from collections.abc import Callable
from dataclasses import dataclass
import datetime
import hashlib
import hmac
import time
from typing import Protocol, cast

from Cryptodome.Cipher import AES

from .models import CodecException, EncryptionKeysAuth


class _CbcCipher(Protocol):
    def encrypt(self, plaintext: bytes) -> bytes: ...


@dataclass(frozen=True)
class FideliusCryptoMaterial:
    database_name: str
    hashed_out_beta_b64: str
    hashed_beta_cipher_b64: str
    out_beta_cipher: bytes
    in_beta_cipher: bytes
    device_user_records_b64: str
    version: int


def encode_varint(value: int) -> bytes:
    if value < 0:
        raise CodecException("INVALID_VARINT", f"Cannot encode negative varint: {value}")
    out = bytearray()
    rem = value
    while rem > 0x7F:
        out.append((rem & 0x7F) | 0x80)
        rem >>= 7
    out.append(rem & 0x7F)
    return bytes(out)


def decode_b64_flexible(value: str) -> bytes:
    cleaned = value.strip()
    pad = (-len(cleaned)) % 4
    if pad:
        cleaned += "=" * pad
    try:
        if "-" in cleaned or "_" in cleaned:
            return base64.urlsafe_b64decode(cleaned)
        return base64.b64decode(cleaned)
    except Exception as exc:
        raise CodecException("BASE64_DECODE_FAILED", f"Failed to decode base64 value ({len(value)} chars)", exc) from exc


def _pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
    pad_len = block_size - (len(data) % block_size)
    return data + bytes([pad_len] * pad_len)


def aes_256_cbc_encrypt_zero_iv(key: bytes, plaintext: bytes) -> bytes:
    if len(key) != 32:
        raise CodecException("INVALID_AES_KEY", f"Expected 32-byte IWEK key, got {len(key)} bytes")
    try:
        new_cipher = cast(Callable[[bytes, int, bytes], _CbcCipher], getattr(AES, "new"))
        cipher = new_cipher(key, AES.MODE_CBC, b"\x00" * 16)
        return cipher.encrypt(_pkcs7_pad(plaintext, 16))
    except Exception as exc:
        raise CodecException("AES_ENCRYPT_FAILED", "AES-256-CBC encryption failed", exc) from exc


def build_fidelius_device_user_records_pb(hashed_out_beta_raw: bytes, database_name: str) -> str:
    db_bytes = database_name.encode("utf-8")
    inner = (
        b"\x0a"
        + encode_varint(len(hashed_out_beta_raw))
        + hashed_out_beta_raw
        + b"\x12"
        + encode_varint(len(db_bytes))
        + db_bytes
    )
    outer = b"\x0a" + encode_varint(len(inner)) + inner
    return base64.b64encode(outer).decode("ascii")


def compute_fidelius_material(
    keys: EncryptionKeysAuth,
    fidelius_db_name: str,
) -> FideliusCryptoMaterial:
    iwek_raw = decode_b64_flexible(keys.iwek)
    out_beta_raw = decode_b64_flexible(keys.public_key)
    in_beta_raw = decode_b64_flexible(keys.private_key)

    hashed_out_beta_raw = hmac.new(iwek_raw, out_beta_raw, hashlib.sha256).digest()
    hashed_out_beta_b64 = base64.b64encode(hashed_out_beta_raw).decode("ascii")

    hashed_beta_cipher = aes_256_cbc_encrypt_zero_iv(iwek_raw, hashed_out_beta_b64.encode("ascii"))
    out_beta_cipher = aes_256_cbc_encrypt_zero_iv(iwek_raw, out_beta_raw)
    in_beta_cipher = aes_256_cbc_encrypt_zero_iv(iwek_raw, in_beta_raw)
    records_b64 = build_fidelius_device_user_records_pb(hashed_out_beta_raw, fidelius_db_name)

    return FideliusCryptoMaterial(
        database_name=fidelius_db_name,
        hashed_out_beta_b64=hashed_out_beta_b64,
        hashed_beta_cipher_b64=base64.b64encode(hashed_beta_cipher).decode("ascii"),
        out_beta_cipher=out_beta_cipher,
        in_beta_cipher=in_beta_cipher,
        device_user_records_b64=records_b64,
        version=keys.version,
    )


def build_argos_token_bin(token_b64: str, refresh_at_iso: str) -> bytes:
    token_raw = decode_b64_flexible(token_b64)
    now_sec = int(time.time())
    ttl_sec = 101346
    if refresh_at_iso:
        try:
            norm = refresh_at_iso.replace("Z", "+00:00")
            refresh_dt = datetime.datetime.fromisoformat(norm)
            refresh_ts = int(refresh_dt.timestamp())
            if refresh_ts > now_sec + 3600:
                ttl_sec = max(3600, refresh_ts - now_sec)
        except Exception:
            pass
    inner = (
        b"\x0a"
        + encode_varint(len(token_raw))
        + token_raw
        + b"\x10"
        + encode_varint(ttl_sec)
        + b"\x20\x06"
    )
    return b"\x0a" + encode_varint(len(inner)) + inner + b"\x10" + encode_varint(now_sec)


def synthesize_birthday(age: int, astrological_sign: int) -> str:
    sign_month_day: dict[int, tuple[int, int]] = {
        1: (4, 5),
        2: (5, 5),
        3: (6, 5),
        4: (7, 5),
        5: (8, 5),
        6: (9, 5),
        7: (10, 5),
        8: (11, 5),
        9: (12, 5),
        10: (1, 5),
        11: (2, 5),
        12: (3, 5),
    }
    month, day = sign_month_day.get(astrological_sign, (11, 5))
    today = datetime.date.today()
    safe_age = max(18, min(65, age if age > 0 else 20))
    birth_year = today.year - safe_age
    if (today.month, today.day) < (month, day):
        birth_year -= 1
    return f"{birth_year:04d}-{month:02d}-{day:02d}"
