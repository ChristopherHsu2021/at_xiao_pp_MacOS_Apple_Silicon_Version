"""Hidden admin authentication helpers."""

from __future__ import annotations

import base64


_KEY = b"AT_XIAOPP_ADMIN_KEY"
_ENCRYPTED_PASSWORD = "AjwtMTpxfGBhb3k="


def _xor(data: bytes) -> bytes:
    return bytes(value ^ _KEY[index % len(_KEY)] for index, value in enumerate(data))


def decrypt_admin_password() -> str:
    return _xor(base64.b64decode(_ENCRYPTED_PASSWORD)).decode("utf-8")


def verify_admin_password(password: str) -> bool:
    return password == decrypt_admin_password()
