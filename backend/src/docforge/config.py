"""Configuration (T014).

Pydantic settings for DB / Redis / object store / CDN / signing. In the MVP slice
only a subset is consumed (object-store base URL + URL TTL); the rest document the
production surface.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    # default_factory so each Settings() reads the environment at construction time,
    # not once at import time.
    cdn_base_url: str = field(
        default_factory=lambda: os.getenv("DOCFORGE_CDN_BASE_URL", "https://cdn.local")
    )
    signed_url_ttl_seconds: int = field(
        default_factory=lambda: int(os.getenv("DOCFORGE_SIGNED_URL_TTL", "300"))
    )
    # Dev auth (Bearer <user_id>) is fail-closed: it only works when explicitly
    # enabled. Set DOCFORGE_DEV_AUTH=false to disable it so the placeholder auth
    # can never silently ship to production (C5).
    dev_auth_enabled: bool = field(
        default_factory=lambda: os.getenv("DOCFORGE_DEV_AUTH", "true").lower() != "false"
    )
    # Production-only (unused in the in-memory MVP slice):
    database_url: str | None = field(default_factory=lambda: os.getenv("DOCFORGE_DATABASE_URL"))
    redis_url: str | None = field(default_factory=lambda: os.getenv("DOCFORGE_REDIS_URL"))
    object_store_bucket: str | None = field(default_factory=lambda: os.getenv("DOCFORGE_BUCKET"))


def get_settings() -> Settings:
    return Settings()
