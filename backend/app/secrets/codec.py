"""Version 1 authenticated envelopes. Keep this format readable by migrations."""

import base64
import json
import os
import re
import stat
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.exc import DontWrapMixin

MAX_KEYRING_BYTES = 16_384
KEY_ID = re.compile(r"[a-zA-Z0-9_-]{1,64}\Z")


class SecretStorageError(RuntimeError, DontWrapMixin):
    """Deliberately contains neither file contents, ciphertext nor plaintext."""

    def __init__(self):
        super().__init__("Secret storage is unavailable; check the private keyring.")


def read_private_file(path: str, limit: int) -> bytes:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                raise SecretStorageError()
            data = source.read(limit + 1)
            if len(data) > limit:
                raise SecretStorageError()
            return data
    except (OSError, ValueError):
        raise SecretStorageError() from None


def new_keyring() -> dict:
    key_id = os.urandom(8).hex()
    return {
        "active": key_id,
        "keys": {key_id: base64.b64encode(os.urandom(32)).decode()},
    }


def write_keyring(path: Path, value: dict) -> None:
    # No overwrite or symlink following; no window with public permissions.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(value, output)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


class Keyring:
    def __init__(self, path: str):
        try:
            value = json.loads(read_private_file(path, MAX_KEYRING_BYTES))
            self.active = value["active"]
            encoded = value["keys"]
            if not isinstance(encoded, dict) or not 1 <= len(encoded) <= 32:
                raise ValueError()
            self.keys = {}
            for key_id, key in encoded.items():
                if not KEY_ID.fullmatch(key_id):
                    raise ValueError()
                decoded = base64.b64decode(key, validate=True)
                if len(decoded) != 32:
                    raise ValueError()
                self.keys[key_id] = decoded
            if self.active not in self.keys:
                raise ValueError()
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
            raise SecretStorageError() from None

    def seal(self, plaintext: str, purpose: str) -> str:
        nonce = os.urandom(12)
        header = f"sntenc1:{self.active}"
        encrypted = AESGCM(self.keys[self.active]).encrypt(
            nonce, plaintext.encode(), f"{header}:{purpose}".encode()
        )
        return f"{header}:{base64.b64encode(nonce + encrypted).decode()}"

    def open(self, envelope: str, purpose: str) -> str:
        try:
            version, key_id, encoded = envelope.split(":")
            if version != "sntenc1":
                raise ValueError()
            data = base64.b64decode(encoded, validate=True)
            return (
                AESGCM(self.keys[key_id])
                .decrypt(data[:12], data[12:], f"{version}:{key_id}:{purpose}".encode())
                .decode()
            )
        except (ValueError, KeyError, TypeError, AttributeError, InvalidTag):
            raise SecretStorageError() from None


def configured_keyring() -> Keyring:
    from app.core.config import get_settings

    return Keyring(get_settings().secret_keyring_file)
