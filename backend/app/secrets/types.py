"""Encrypt at the SQL bind boundary, including ORM and Core writes."""

import json

from sqlalchemy import JSON, Text, TypeDecorator

from app.secrets.codec import SecretStorageError, configured_keyring


class EncryptedKey(TypeDecorator):
    purpose = "target-api-key"
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return (
            configured_keyring().seal(value, self.purpose)
            if value is not None
            else None
        )

    def process_result_value(self, value, dialect):
        return (
            configured_keyring().open(value, self.purpose)
            if value is not None
            else None
        )


class EncryptedProviderKey(EncryptedKey):
    purpose = "provider-api-key"
    cache_ok = True


class EncryptedPayload(TypeDecorator):
    # Preserve the existing JSON column and SQL/JSON null terminal cleanup behavior.
    impl = JSON
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return {
            "encrypted": configured_keyring().seal(json.dumps(value), "job-payload")
        }

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            if set(value) != {"encrypted"}:
                raise SecretStorageError()
            return json.loads(
                configured_keyring().open(value["encrypted"], "job-payload")
            )
        except (ValueError, TypeError):
            raise SecretStorageError() from None
