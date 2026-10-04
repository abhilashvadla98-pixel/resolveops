import json
from enum import Enum
from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL
from sqlalchemy.engine import make_url


class RuntimeEnvironment(str, Enum):
    DEVELOPMENT = "development"
    DEMO = "demo"
    PRODUCTION = "production"


class RuntimeSafetyError(ValueError):
    pass


class RuntimeModeSettings(BaseSettings):
    environment: RuntimeEnvironment = RuntimeEnvironment.DEVELOPMENT

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="RESOLVEOPS_",
        extra="ignore",
        hide_input_in_errors=True,
    )


class Settings(BaseSettings):
    environment: RuntimeEnvironment = RuntimeEnvironment.DEVELOPMENT
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
    agent_max_output_tokens: int = Field(default=1_600, ge=100, le=4_096)
    gemini_key_rotated: bool = False
    integrated_agents_enabled: bool = False
    demo_agent_max_runs_per_session: int = Field(default=0, ge=0, le=5)
    demo_agent_global_cooldown_seconds: int = Field(default=0, ge=0, le=3_600)
    agent_queue_enabled: bool = False
    agent_queue_capacity: int = Field(default=500, ge=10, le=100_000)
    agent_job_lease_seconds: int = Field(default=120, ge=30, le=3_600)
    agent_job_max_attempts: int = Field(default=2, ge=1, le=5)
    agent_worker_poll_seconds: int = Field(default=5, ge=1, le=60)
    redis_url: str | None = None
    agent_reviewed_memory_enabled: bool = True
    agent_mcp_server_url: str | None = None
    agent_mcp_timeout_seconds: float = Field(default=5, gt=0, le=30)
    agent_input_cost_per_million_usd: float | None = Field(default=None, ge=0)
    agent_output_cost_per_million_usd: float | None = Field(default=None, ge=0)
    agent_cost_limit_usd: float | None = Field(default=None, gt=0, le=100)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="RESOLVEOPS_",
        extra="ignore",
        hide_input_in_errors=True,
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

    @model_validator(mode="after")
    def validate_agent_pricing(self) -> "Settings":
        if (self.agent_input_cost_per_million_usd is None) != (
            self.agent_output_cost_per_million_usd is None
        ):
            raise ValueError("agent input and output pricing must be configured together")
        if self.integrated_agents_enabled and self.gemini_api_key is None:
            raise ValueError("integrated agents require a configured Gemini API key")
        if self.integrated_agents_enabled and not self.gemini_key_rotated:
            raise ValueError("integrated agents require confirmed Gemini key rotation")
        return self

    def resolved_database_url(self) -> str:
        if self.database_url is not None:
            return _normalize_postgresql_driver(self.database_url.get_secret_value())
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
    redis_url: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="RESOLVEOPS_",
        extra="ignore",
        hide_input_in_errors=True,
    )


class ObservabilitySettings(BaseSettings):
    otlp_endpoint: str | None = None
    otlp_service_name: str = Field(default="resolveops", min_length=1, max_length=100)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="RESOLVEOPS_",
        extra="ignore",
        hide_input_in_errors=True,
    )


class DemoSettings(BaseSettings):
    demo_enabled: bool = False
    demo_tenant_id: str = "TENANT-DEMO"
    demo_session_secret: SecretStr | None = None
    demo_session_ttl_seconds: int = Field(default=1800, ge=300, le=3600)
    demo_isolated_sessions: bool = False
    demo_max_isolated_sessions: int = Field(default=8, ge=1, le=64)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="RESOLVEOPS_",
        extra="ignore",
        hide_input_in_errors=True,
    )

    @model_validator(mode="after")
    def validate_demo_configuration(self) -> "DemoSettings":
        if self.demo_enabled and self.demo_session_secret is None:
            raise ValueError("demo_session_secret is required when demo mode is enabled")
        if (
            self.demo_session_secret is not None
            and len(self.demo_session_secret.get_secret_value()) < 32
        ):
            raise ValueError("demo_session_secret must contain at least 32 characters")
        return self


def validate_runtime_safety(settings: Settings, demo_settings: DemoSettings) -> None:
    """Reject known local/example configuration outside development."""
    environment = settings.environment
    if environment == RuntimeEnvironment.DEVELOPMENT:
        return
    _validate_environment_mode(environment, demo_settings)
    _validate_database_configuration(settings)
    _validate_tenant_configuration(settings, demo_settings)
    _validate_webhook_configuration(settings)
    if environment == RuntimeEnvironment.PRODUCTION:
        _validate_production_identities(settings)


def _validate_environment_mode(
    environment: RuntimeEnvironment, demo_settings: DemoSettings
) -> None:
    if environment == RuntimeEnvironment.DEMO and not demo_settings.demo_enabled:
        raise RuntimeSafetyError("demo environment requires restricted demo sessions")
    if environment == RuntimeEnvironment.DEMO and not demo_settings.demo_isolated_sessions:
        raise RuntimeSafetyError("demo environment requires isolated per-session workspaces")
    if environment == RuntimeEnvironment.PRODUCTION and demo_settings.demo_enabled:
        raise RuntimeSafetyError("production environment cannot enable the public demo workspace")


def _validate_database_configuration(settings: Settings) -> None:
    database_urls = [settings.resolved_database_url()]
    if settings.tenant_database_urls_json is not None:
        try:
            tenant_urls = json.loads(settings.tenant_database_urls_json.get_secret_value())
        except json.JSONDecodeError as exc:
            raise RuntimeSafetyError("tenant database configuration must be valid JSON") from exc
        if not isinstance(tenant_urls, dict) or not tenant_urls:
            raise RuntimeSafetyError("non-development tenant database mapping cannot be empty")
        database_urls.extend(str(value) for value in tenant_urls.values())
    for database_url in database_urls:
        parsed = make_url(database_url)
        unsafe_database = (
            parsed.get_backend_name() == "sqlite"
            or parsed.host in {None, "localhost", "127.0.0.1", "database"}
            or _contains_placeholder(database_url)
        )
        if unsafe_database:
            raise RuntimeSafetyError("non-development database configuration is unsafe")


def _validate_tenant_configuration(settings: Settings, demo_settings: DemoSettings) -> None:
    if settings.default_tenant_id == "TENANT-LOCAL":
        raise RuntimeSafetyError("non-development environment cannot use TENANT-LOCAL")
    if (
        settings.environment == RuntimeEnvironment.DEMO
        and settings.default_tenant_id != demo_settings.demo_tenant_id
    ):
        raise RuntimeSafetyError("demo environment must route only to the synthetic demo tenant")


def _validate_webhook_configuration(settings: Settings) -> None:
    webhook_values = []
    if settings.webhook_secret is not None:
        webhook_values.append(settings.webhook_secret.get_secret_value())
    if settings.webhook_secrets_json is not None:
        webhook_values.append(settings.webhook_secrets_json.get_secret_value())
    if not webhook_values or any(_contains_placeholder(value) for value in webhook_values):
        raise RuntimeSafetyError("non-development webhook secrets must be configured")


def _validate_production_identities(settings: Settings) -> None:
    if settings.agent_mcp_server_url is not None:
        raise RuntimeSafetyError(
            "production external MCP requires an authenticated tenant transport"
        )
    if settings.api_key_identities_json is None:
        raise RuntimeSafetyError("production requires at least one enabled API identity")
    try:
        identities = json.loads(settings.api_key_identities_json.get_secret_value())
    except json.JSONDecodeError as exc:
        raise RuntimeSafetyError("API identity configuration must be valid JSON") from exc
    if not isinstance(identities, list) or not any(
        isinstance(identity, dict)
        and identity.get("enabled") is True
        and identity.get("key_sha256") != "0" * 64
        for identity in identities
    ):
        raise RuntimeSafetyError(
            "production requires at least one non-example enabled API identity"
        )


def _contains_placeholder(value: str) -> bool:
    normalized = value.lower()
    return any(
        marker in normalized
        for marker in ("replace-me", "replace-with", "change-me", "example.", "example/")
    )


def _normalize_postgresql_driver(database_url: str) -> str:
    """Use the installed psycopg v3 driver for platform-provided PostgreSQL URLs."""
    parsed = make_url(database_url)
    if parsed.drivername in {"postgres", "postgresql"}:
        parsed = parsed.set(drivername="postgresql+psycopg")
    return parsed.render_as_string(hide_password=False)


def validate_startup_environment() -> None:
    """Keep configuration-free health/test imports in development only."""
    mode = RuntimeModeSettings().environment
    if mode == RuntimeEnvironment.DEVELOPMENT:
        return
    validate_runtime_safety(get_settings(), get_demo_settings())


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_traffic_protection_settings() -> TrafficProtectionSettings:
    return TrafficProtectionSettings()


@lru_cache
def get_observability_settings() -> ObservabilitySettings:
    return ObservabilitySettings()


@lru_cache
def get_demo_settings() -> DemoSettings:
    return DemoSettings()
