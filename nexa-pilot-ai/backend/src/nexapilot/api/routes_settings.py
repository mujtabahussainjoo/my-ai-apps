"""Settings and provider routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from nexapilot.api.deps import ContainerDep, SessionDep
from nexapilot.core.container import Container
from nexapilot.core.errors import ConfigurationError
from nexapilot.core.secrets import describe_backend
from nexapilot.db.models import ProviderConfig
from nexapilot.providers.base import ProviderCapabilities
from nexapilot.providers.registry import build_provider, list_provider_specs
from nexapilot.schemas.providers import (
    ActiveProviderSchema,
    ProviderConfigRequest,
    ProviderConfigSchema,
    ProviderSpecSchema,
)

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/providers", response_model=list[ProviderSpecSchema])
def list_providers() -> list[dict[str, Any]]:
    return [spec.to_dict() for spec in list_provider_specs()]


@router.get("/providers/active", response_model=ActiveProviderSchema)
def get_active_provider(
    session: Session = SessionDep, container: Container = ContainerDep
) -> ActiveProviderSchema:
    from nexapilot.services.provider_settings import get_active_config

    config = get_active_config(session)
    if config is None:
        return ActiveProviderSchema(
            is_configured=False,
            detail={"message": "No provider is active. Choose one and press Save & Activate."},
        )
    has_secret = bool(config.secret_reference and container.secrets.get(config.secret_reference))
    return ActiveProviderSchema(
        provider=config.provider,
        model=config.model,
        base_url=config.base_url,
        capabilities=ProviderCapabilities(**(config.capabilities or {})),
        is_configured=has_secret or not config.secret_reference,
        detail={"has_secret": has_secret},
    )


@router.get("/providers/configs", response_model=list[ProviderConfigSchema])
def list_provider_configs(
    session: Session = SessionDep, container: Container = ContainerDep
) -> list[ProviderConfigSchema]:
    from nexapilot.services.provider_settings import list_configs

    configs = list_configs(session)
    return [
        ProviderConfigSchema(
            id=config.id,
            provider=config.provider,
            model=config.model,
            base_url=config.base_url,
            auth_mode=config.auth_mode,
            capabilities=ProviderCapabilities(**(config.capabilities or {})),
            is_active=config.is_active,
            has_secret=bool(
                config.secret_reference and container.secrets.get(config.secret_reference)
            ),
            secret_reference=config.secret_reference,
        )
        for config in configs
    ]


@router.post("/providers/configs", response_model=ProviderConfigSchema)
def save_provider_config(
    payload: ProviderConfigRequest,
    session: Session = SessionDep,
    container: Container = ContainerDep,
) -> ProviderConfigSchema:
    """Save a configuration without activating it."""
    from nexapilot.services.provider_settings import save_config

    try:
        config = save_config(session, container.secrets, payload)
    except ConfigurationError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.to_payload()) from exc
    session.commit()
    return ProviderConfigSchema(
        id=config.id,
        provider=config.provider,
        model=config.model,
        base_url=config.base_url,
        auth_mode=config.auth_mode,
        capabilities=ProviderCapabilities(**(config.capabilities or {})),
        is_active=config.is_active,
        has_secret=bool(config.secret_reference and container.secrets.get(config.secret_reference)),
        secret_reference=config.secret_reference,
    )


@router.delete("/providers/configs/{config_id}")
def delete_provider_config(
    config_id: str,
    session: Session = SessionDep,
    container: Container = ContainerDep,
) -> dict[str, Any]:
    from nexapilot.core.errors import NotFoundError
    from nexapilot.services.provider_settings import delete_config

    config = session.get(ProviderConfig, config_id)
    if config is None:
        raise NotFoundError(f"Provider configuration '{config_id}' not found")
    delete_config(session, container.secrets, config)
    session.commit()
    return {"status": "deleted", "id": config_id}


@router.post("/providers/configs/{config_id}/activate", response_model=ProviderConfigSchema)
async def activate_saved_config(
    config_id: str,
    session: Session = SessionDep,
    container: Container = ContainerDep,
) -> ProviderConfigSchema:
    from nexapilot.core.errors import NotFoundError
    from nexapilot.services.provider_settings import activate_existing

    config = session.get(ProviderConfig, config_id)
    if config is None:
        raise NotFoundError(f"Provider configuration '{config_id}' not found")
    try:
        config = await activate_existing(session, container.secrets, config)
    except ConfigurationError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.to_payload()) from exc
    session.commit()
    return ProviderConfigSchema(
        id=config.id,
        provider=config.provider,
        model=config.model,
        base_url=config.base_url,
        auth_mode=config.auth_mode,
        capabilities=ProviderCapabilities(**(config.capabilities or {})),
        is_active=config.is_active,
        has_secret=bool(config.secret_reference and container.secrets.get(config.secret_reference)),
        secret_reference=config.secret_reference,
    )


@router.post("/providers/test")
async def test_provider(
    payload: ProviderConfigRequest, container: Container = ContainerDep
) -> dict[str, Any]:
    """Validate a configuration without saving it."""
    spec = build_provider(
        payload.provider,
        model=payload.model,
        base_url=payload.base_url,
        api_key=payload.api_key or "",
    )
    result = await spec.test_connection()
    return result.model_dump()


@router.post("/providers/activate", response_model=ProviderConfigSchema)
async def activate_provider(
    payload: ProviderConfigRequest,
    session: Session = SessionDep,
    container: Container = ContainerDep,
) -> ProviderConfigSchema:
    from nexapilot.services.provider_settings import activate_config

    try:
        config = await activate_config(session, container.secrets, payload)
    except ConfigurationError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.to_payload()) from exc
    session.commit()
    return ProviderConfigSchema(
        id=config.id,
        provider=config.provider,
        model=config.model,
        base_url=config.base_url,
        auth_mode=config.auth_mode,
        capabilities=ProviderCapabilities(**(config.capabilities or {})),
        is_active=config.is_active,
        has_secret=bool(config.secret_reference and container.secrets.get(config.secret_reference)),
        secret_reference=config.secret_reference,
    )


@router.get("/settings")
def get_settings(container: Container = ContainerDep) -> dict[str, Any]:
    from nexapilot.services.provider_settings import get_active_config

    settings = container.settings
    session = container.session_factory()
    try:
        active_config = get_active_config(session)
    finally:
        session.close()
    return {
        "app_name": settings.app_name,
        "environment": settings.environment,
        "active_provider": active_config.provider if active_config else "",
        "active_model": active_config.model if active_config else "",
        "active_provider_configured": active_config is not None,
        "integrations": {
            "web_search": {
                "provider": settings.web_search_provider,
                "configured": bool(settings.web_search_provider),
            },
            "travel": {
                "provider": settings.travel_provider,
                "configured": bool(settings.travel_provider),
            },
            "finance": {
                "provider": settings.finance_provider,
                "configured": bool(settings.finance_provider),
                "broker_configured": bool(settings.finance_broker_base_url),
            },
            "email": {
                "oauth_client_configured": bool(container.secrets.get("google:oauth:client_id"))
            },
        },
        "coding": {
            "workspace_root": settings.coding_workspace_root,
            "workspace_configured": bool(settings.coding_workspace_root),
            "max_output_bytes": settings.coding_max_output_bytes,
        },
        "security": {
            "secret_backend": describe_backend(container.secrets),
            "api_bound_to": f"{settings.host}:{settings.port}",
        },
        "limits": {
            "max_tool_iterations": settings.max_tool_iterations,
            "max_agent_steps": settings.max_agent_steps,
            "finance_max_order_value": settings.finance_max_order_value,
            "finance_max_order_quantity": settings.finance_max_order_quantity,
        },
    }


@router.patch("/settings")
async def update_settings(
    payload: dict[str, Any], container: Container = ContainerDep
) -> dict[str, Any]:
    """Update the mutable parts of the runtime configuration and persist them."""
    from nexapilot.core.settings_store import MUTABLE_SETTINGS, save_overrides

    unknown = sorted(set(payload) - MUTABLE_SETTINGS)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "validation_error",
                "message": f"Unknown settings: {', '.join(unknown)}",
            },
        )
    updated: dict[str, Any] = {}
    for key, value in payload.items():
        current = getattr(container.settings, key)
        try:
            coerced = type(current)(value) if not isinstance(current, bool) else _as_bool(value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "validation_error", "message": f"Invalid value for {key}: {exc}"},
            ) from exc
        setattr(container.settings, key, coerced)
        updated[key] = coerced
    save_overrides(updated)
    return {"status": "updated", "updated": updated, "settings": get_settings(container)}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


KNOWN_SECRETS: dict[str, str] = {
    "google:oauth:client_id": "Google OAuth client id",
    "google:oauth:client_secret": "Google OAuth client secret",
    "search:brave:api_key": "Brave Search API key",
    "search:tavily:api_key": "Tavily API key",
    "search:searxng:api_key": "SearXNG API key (optional)",
    "travel:amadeus:api_key": "Amadeus API key (client id)",
    "travel:amadeus:api_secret": "Amadeus API secret",
    "finance:broker:api_key": "Broker API key",
}


class SecretValueSchema(BaseModel):
    value: str = Field(min_length=1, max_length=8000)


@router.get("/settings/secrets")
def list_secret_status(container: Container = ContainerDep) -> list[dict[str, Any]]:
    """Report which integration secrets exist. Values are never returned."""
    return [
        {
            "name": name,
            "label": label,
            "configured": bool(container.secrets.get(name)),
        }
        for name, label in KNOWN_SECRETS.items()
    ]


@router.put("/settings/secrets/{name}")
def set_secret(
    name: str, payload: SecretValueSchema, container: Container = ContainerDep
) -> dict[str, Any]:
    if name not in KNOWN_SECRETS:
        raise ConfigurationError(f"Unknown secret '{name}'")
    container.secrets.set(name, payload.value.strip())
    return {"status": "stored", "name": name}


@router.delete("/settings/secrets/{name}")
def delete_secret(name: str, container: Container = ContainerDep) -> dict[str, Any]:
    if name not in KNOWN_SECRETS:
        raise ConfigurationError(f"Unknown secret '{name}'")
    container.secrets.delete(name)
    return {"status": "deleted", "name": name}
