"""Environment-backed application settings."""

import json
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

from app.network.policy import EgressPolicy


class Settings(BaseSettings):
    """Runtime configuration.

    Values are deliberately read from the environment instead of being embedded
    in code. The API does not expose this object, because it may eventually hold
    references to secret-management services.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Sentinel API"
    app_environment: str = "development"
    auth_mode: Literal["local", "token"] = "local"
    database_url: str = "sqlite:///./sentinel.db"
    # Component settings avoid unsafe string interpolation when database passwords
    # contain URL-reserved characters. DATABASE_URL remains supported when no host
    # is supplied (and is the convenient SQLite/test path).
    database_driver: str = "postgresql+psycopg"
    database_host: str | None = None
    database_port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = "sentinel"
    database_user: str = "sentinel"
    database_password: SecretStr | None = Field(default=None, repr=False)
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    target_request_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    target_max_response_bytes: int = Field(default=1_000_000, ge=1_024, le=10_000_000)
    target_egress_rules: dict[str, list[str]] = Field(default_factory=dict)
    # Resource limits applied before JSON parsing and at queued admission.
    max_request_body_bytes: int = Field(default=1_048_576, ge=65_536, le=10_485_760)
    queue_max_active_runs_per_project: int = Field(default=10, ge=1, le=1_000)
    queue_max_active_runs: int = Field(default=50, ge=1, le=10_000)
    judge_egress_rules: dict[str, list[str]] = Field(
        default_factory=lambda: {"https://api.openai.com": []}
    )
    sql_echo: bool = False
    secret_keyring_file: str = ".secrets/keyring.json"
    judge_enabled: bool = False
    openai_api_key: SecretStr | None = Field(default=None, repr=False)
    judge_model: str = ""
    judge_timeout_seconds: float = Field(default=20, ge=1, le=30)
    judge_cache_path: str = ".sentinel-judge-cache.sqlite3"
    judge_input_usd_per_million: float | None = Field(
        default=None, ge=0, le=10000, allow_inf_nan=False
    )
    judge_output_usd_per_million: float | None = Field(
        default=None, ge=0, le=10000, allow_inf_nan=False
    )
    judge_price_version: str = Field(default="unconfigured", max_length=100)

    @field_validator("target_egress_rules", "judge_egress_rules")
    @classmethod
    def validate_egress_rules(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        EgressPolicy(value)
        return value

    @model_validator(mode="after")
    def restrict_local_access(self):
        if self.auth_mode == "local" and self.app_environment != "development":
            raise ValueError("Local access mode is only allowed in development.")
        return self

    @model_validator(mode="after")
    def consistent_queue_limits(self):
        if self.queue_max_active_runs_per_project > self.queue_max_active_runs:
            raise ValueError(
                "The per-project queue limit cannot exceed the installation limit."
            )
        return self

    @field_validator(
        "judge_input_usd_per_million", "judge_output_usd_per_million", mode="before"
    )
    @classmethod
    def empty_price_is_unknown(cls, value):
        return None if value == "" else value

    @property
    def parsed_cors_origins(self) -> list[str]:
        """Return normalized origins from a comma-separated environment value."""

        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]

    @property
    def resolved_database_url(self) -> str | URL:
        """Return a safely constructed database URL for the selected configuration."""

        if self.database_host is None:
            return self.database_url
        return URL.create(
            drivername=self.database_driver,
            username=self.database_user,
            password=(
                self.database_password.get_secret_value()
                if self.database_password is not None
                else None
            ),
            host=self.database_host,
            port=self.database_port,
            database=self.database_name,
        )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide immutable settings snapshot."""

    return Settings()


def egress_environment() -> dict[str, str]:
    """Pass current operator policy, never job-supplied grants, to isolated children."""
    settings = get_settings()
    return {
        "TARGET_EGRESS_RULES": json.dumps(settings.target_egress_rules),
        "JUDGE_EGRESS_RULES": json.dumps(settings.judge_egress_rules),
    }
