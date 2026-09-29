import json

import pytest

from resolveops.config import (
    DemoSettings,
    RuntimeEnvironment,
    RuntimeSafetyError,
    Settings,
    validate_runtime_safety,
)

SAFE_DATABASE = "postgresql+psycopg://service:strong-password@db.internal/resolveops"
SAFE_WEBHOOK = "strong-webhook-secret-with-more-than-32-characters"
SAFE_DEMO_SECRET = "strong-demo-session-secret-with-more-than-32-characters"


def settings(environment: RuntimeEnvironment, **changes: object) -> Settings:
    values: dict[str, object] = {
        "environment": environment,
        "database_url": SAFE_DATABASE,
        "default_tenant_id": "TENANT-PROD",
        "webhook_secret": SAFE_WEBHOOK,
        "api_key_identities_json": json.dumps(
            [
                {
                    "key_sha256": "a" * 64,
                    "subject_id": "SYSTEM-1",
                    "tenant_id": "TENANT-PROD",
                    "role": "system",
                    "enabled": True,
                }
            ]
        ),
    }
    values.update(changes)
    return Settings(**values)


def test_development_allows_documented_local_defaults() -> None:
    local = Settings(
        environment=RuntimeEnvironment.DEVELOPMENT,
        database_url="sqlite:///local.db",
        default_tenant_id="TENANT-LOCAL",
    )

    validate_runtime_safety(local, DemoSettings())


@pytest.mark.parametrize(
    "changes",
    [
        {"database_url": "sqlite:///unsafe.db"},
        {"database_url": "postgresql+psycopg://user:pass@localhost/resolveops"},
        {"database_url": "postgresql+psycopg://user:replace-me@db.internal/resolveops"},
        {"default_tenant_id": "TENANT-LOCAL"},
        {"webhook_secret": "replace-with-a-real-secret"},
        {"api_key_identities_json": "[]"},
        {"api_key_identities_json": json.dumps([{"key_sha256": "0" * 64, "enabled": True}])},
    ],
)
def test_production_rejects_known_unsafe_configuration(changes: dict[str, object]) -> None:
    with pytest.raises(RuntimeSafetyError):
        validate_runtime_safety(settings(RuntimeEnvironment.PRODUCTION, **changes), DemoSettings())


def test_production_rejects_demo_mode() -> None:
    with pytest.raises(RuntimeSafetyError, match="cannot enable"):
        validate_runtime_safety(
            settings(RuntimeEnvironment.PRODUCTION),
            DemoSettings(demo_enabled=True, demo_session_secret=SAFE_DEMO_SECRET),
        )


def test_safe_production_configuration_passes() -> None:
    validate_runtime_safety(settings(RuntimeEnvironment.PRODUCTION), DemoSettings())


def test_demo_environment_is_restricted_to_synthetic_tenant() -> None:
    demo = DemoSettings(demo_enabled=True, demo_session_secret=SAFE_DEMO_SECRET)
    demo_settings = settings(
        RuntimeEnvironment.DEMO,
        default_tenant_id="TENANT-DEMO",
        api_key_identities_json="[]",
    )

    validate_runtime_safety(demo_settings, demo)

    with pytest.raises(RuntimeSafetyError, match="synthetic demo tenant"):
        validate_runtime_safety(
            settings(RuntimeEnvironment.DEMO, default_tenant_id="TENANT-OTHER"),
            demo,
        )
