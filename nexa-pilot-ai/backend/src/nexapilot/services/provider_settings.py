"""Provider configuration and activation.

Enforces the product rule: **exactly one active provider at a time**, never a
silent fallback to another provider.
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from nexapilot.core.errors import ConfigurationError
from nexapilot.core.logging import get_logger
from nexapilot.core.secrets import SecretStore
from nexapilot.db.models import ProviderConfig, SecretReference
from nexapilot.providers.base import Provider
from nexapilot.providers.registry import build_provider, get_provider_spec
from nexapilot.schemas.providers import ProviderConfigRequest

log = get_logger(__name__)


def secret_reference_for(provider: str) -> str:
    return f"provider:{provider}:api_key"


def list_configs(session: Session) -> list[ProviderConfig]:
    return list(session.scalars(select(ProviderConfig).order_by(ProviderConfig.provider)))


def get_active_config(session: Session) -> ProviderConfig | None:
    return session.scalars(select(ProviderConfig).where(ProviderConfig.is_active.is_(True))).first()


def get_config(session: Session, provider: str) -> ProviderConfig | None:
    return session.scalars(
        select(ProviderConfig).where(ProviderConfig.provider == provider)
    ).first()


def _store_secret(
    session: Session, secrets: SecretStore, provider: str, api_key: str | None
) -> str:
    reference = secret_reference_for(provider)
    if api_key is None:
        return reference
    secrets.set(reference, api_key)
    session.merge(
        SecretReference(
            reference=reference,
            provider=provider,
            label=f"{provider} API key",
        )
    )
    return reference


def save_config(
    session: Session,
    secrets: SecretStore,
    request: ProviderConfigRequest,
) -> ProviderConfig:
    """Save (or update) a provider configuration without activating it."""
    spec = get_provider_spec(request.provider)

    if request.auth_mode == "none" and spec.requires_api_key:
        raise ConfigurationError(
            f"Provider '{request.provider}' requires an API key",
            details={"provider": request.provider},
        )
    if request.auth_mode not in spec.supported_auth_modes:
        raise ConfigurationError(
            f"Provider '{request.provider}' does not support auth mode '{request.auth_mode}'",
            details={"supported": list(spec.supported_auth_modes)},
        )
    if spec.requires_api_key and not request.api_key:
        existing = get_config(session, request.provider)
        if existing is None or not existing.secret_reference:
            raise ConfigurationError(
                f"Provider '{request.provider}' requires an API key",
                details={"provider": request.provider},
            )
    if request.base_url and not spec.supports_custom_base_url:
        raise ConfigurationError(
            f"Provider '{request.provider}' does not support a custom base URL",
            details={"provider": request.provider},
        )

    existing = get_config(session, request.provider)
    if existing is None:
        existing = ProviderConfig(provider=request.provider, model=request.model)
        session.add(existing)

    existing.model = request.model
    existing.base_url = request.base_url or spec.default_base_url
    existing.auth_mode = request.auth_mode
    existing.capabilities = spec.capabilities.model_dump()
    existing.secret_reference = _store_secret(session, secrets, request.provider, request.api_key)
    if not existing.secret_reference:
        existing.secret_reference = secret_reference_for(request.provider)
    return existing


async def activate_config(
    session: Session,
    secrets: SecretStore,
    request: ProviderConfigRequest,
    *,
    validate: bool = True,
) -> ProviderConfig:
    """Validate a provider configuration and, if valid, activate it atomically.

    The previous active provider is deactivated in the same transaction, so there
    is never a moment with two active providers. When validation fails, nothing is
    activated and the previous provider remains active.
    """
    config = save_config(session, secrets, request)
    session.flush()

    if validate:
        provider = build_active_provider(session, secrets, config)
        result = await provider.test_connection()
        if not result.ok:
            raise ConfigurationError(
                f"Provider validation failed: {result.message}",
                details={"provider": request.provider, "error_code": result.error_code},
            )

    session.execute(update(ProviderConfig).values(is_active=False))
    config.is_active = True
    session.flush()
    log.info("provider.activated", provider=config.provider, model=config.model)
    return config


async def activate_existing(
    session: Session,
    secrets: SecretStore,
    config: ProviderConfig,
    *,
    validate: bool = True,
) -> ProviderConfig:
    """Activate an already-saved provider configuration."""
    session.flush()
    if validate:
        provider = build_active_provider(session, secrets, config)
        result = await provider.test_connection()
        if not result.ok:
            raise ConfigurationError(
                f"Provider validation failed: {result.message}",
                details={"provider": config.provider, "error_code": result.error_code},
            )
    session.execute(update(ProviderConfig).values(is_active=False))
    config.is_active = True
    session.flush()
    log.info("provider.activated", provider=config.provider, model=config.model)
    return config


def delete_config(session: Session, secrets: SecretStore, config: ProviderConfig) -> None:
    """Remove a saved configuration and its stored secret."""
    if config.secret_reference:
        secrets.delete(config.secret_reference)
    session.delete(config)
    session.flush()
    log.info("provider.deleted", provider=config.provider)


def build_active_provider(
    session: Session,
    secrets: SecretStore,
    config: ProviderConfig,
) -> Provider:
    """Build the adapter for an explicit configuration row."""
    api_key = ""
    if config.secret_reference:
        api_key = secrets.get(config.secret_reference) or ""
    return build_provider(
        config.provider,
        model=config.model,
        base_url=config.base_url,
        api_key=api_key,
    )


def get_active_provider(session: Session, secrets: SecretStore) -> Provider:
    """Return the single active provider, or raise if none is configured."""
    config = get_active_config(session)
    if config is None:
        raise ConfigurationError(
            "No active model provider is configured. Open Settings and activate a provider.",
            details={"code": "no_active_provider"},
        )
    spec = get_provider_spec(config.provider)
    if spec.requires_api_key:
        reference = config.secret_reference or secret_reference_for(config.provider)
        if not secrets.get(reference):
            raise ConfigurationError(
                f"The active provider '{config.provider}' has no stored API key. "
                "Re-enter the key in Settings and activate the provider again.",
                details={"provider": config.provider},
            )
    return build_active_provider(session, secrets, config)
