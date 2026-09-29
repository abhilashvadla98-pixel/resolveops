from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    database_url: SecretStr | None = None
    database_host: str | None = None
    database_port: int = Field(default=5432, gt=0, le=65535)
    database_name: str | None = None
    database_username: str | None = None
    database_password: SecretStr | None = None
    default_tenant_id: str = "TENANT-LOCAL"
    tenant_database_urls_json: SecretStr | None = None
    api_key_identities_json: SecretStr | None = None
    webhook_secret: SecretStr | None = None
    webhook_secrets_json: SecretStr | None = None
    webhook_tolerance_seconds: int = Field(default=300, gt=0, le=3600)
    gemini_api_key: SecretStr | None = None
    gemini_model: str = Field(default="gemini-3.5-flash-lite", min_length=1, max_length=200)
    gemini_timeout_seconds: int = Field(default=30, gt=0, le=120)
    gemini_max_attempts: int = Field(default=2, ge=1, le=3)
    gemini_max_input_characters: int = Field(default=24_000, ge=1_000, le=100_000)
    gemini_max_output_tokens: int = Field(default=800, ge=100, le=4_096)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="RESOLVEOPS_",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_database_configuration(self) -> "Settings":
        if self.database_url is not None:
            return self
        required = (
            self.database_host,
            self.database_name,
            self.database_username,
            self.database_password,
        )
        if any(value is None for value in required):
            raise ValueError(
                "database_url or database_host, database_name, database_username, "
                "and database_password must be configured"
            )
        return self

    def resolved_database_url(self) -> str:
        if self.database_url is not None:
            return self.database_url.get_secret_value()
        if (
            self.database_host is None
            or self.database_name is None
            or self.database_username is None
            or self.database_password is None
        ):
            raise RuntimeError("database configuration is incomplete")
        return URL.create(
            "postgresql+psycopg",
            username=self.database_username,
            password=self.database_password.get_secret_value(),
            host=self.database_host,
            port=self.database_port,
            database=self.database_name,
        ).render_as_string(hide_password=False)


class TrafficProtectionSettings(BaseSettings):
    max_request_body_bytes: int = Field(default=1_048_576, ge=1_024, le=10_485_760)
    rate_limit_requests: int = Field(default=120, ge=1, le=10_000)
    rate_limit_period_seconds: int = Field(default=60, ge=1, le=3_600)
    rate_limit_max_buckets: int = Field(default=10_000, ge=100, le=1_000_000)
    rate_limit_idle_ttl_seconds: int = Field(default=900, ge=60, le=86_400)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="RESOLVEOPS_",
        extra="ignore",
    )


class DemoSettings(BaseSettings):
    demo_enabled: bool = False
    demo_tenant_id: str = "TENANT-DEMO"
    demo_session_secret: SecretStr | None = None
    demo_session_ttl_seconds: int = Field(default=1800, ge=300, le=3600)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="RESOLVEOPS_",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_demo_configuration(self) -> "DemoSettings":
        if self.demo_enabled and self.demo_session_secret is None:
            raise ValueError("demo_session_secret is required when demo mode is enabled")
        if self.demo_session_secret is not None and len(
            self.demo_session_secret.get_secret_value()
        ) < 32:
            raise ValueError("demo_session_secret must contain at least 32 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_traffic_protection_settings() -> TrafficProtectionSettings:
    return TrafficProtectionSettings()


@lru_cache
def get_demo_settings() -> DemoSettings:
    return DemoSettings()
