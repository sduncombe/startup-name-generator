from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import domains_config, get_settings
from app.services.domain.base import DomainProvider, DomainResult

logger = logging.getLogger(__name__)


class RdapDomainProvider(DomainProvider):
    """
    Registration check via RDAP. Does NOT treat missing DNS as available.
    404 / not-found style RDAP responses → available.
    200 with registration data → registered.
    """

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.settings = get_settings()
        self.cfg = domains_config()
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.settings.domain_check_timeout_seconds,
                headers={"User-Agent": "startup-name-generator/0.1 (internal)"},
                follow_redirects=True,
            )
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _server_for(self, domain: str) -> str | None:
        tld = domain.rsplit(".", 1)[-1].lower()
        servers = self.cfg.get("rdap_servers") or {}
        base = servers.get(tld)
        if not base:
            return None
        return f"{base.rstrip('/')}/domain/{quote(domain.lower())}"

    async def check_domain(self, domain: str) -> DomainResult:
        domain = domain.lower().strip()
        url = self._server_for(domain)
        if not url:
            return DomainResult(
                domain=domain,
                status="unknown",
                detail="No RDAP server configured for this TLD",
            )

        client = await self._get_client()
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
                retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
                reraise=True,
            ):
                with attempt:
                    resp = await client.get(url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("RDAP check failed for %s: %s", domain, type(exc).__name__)
            return DomainResult(
                domain=domain,
                status="error",
                detail=f"RDAP request failed: {type(exc).__name__}",
            )

        if resp.status_code == 404:
            return DomainResult(
                domain=domain,
                status="available",
                detail="RDAP: not found (likely available)",
                raw={"status_code": 404},
            )

        if resp.status_code == 200:
            data: dict[str, Any]
            try:
                data = resp.json()
            except Exception:  # noqa: BLE001
                data = {}
            status, detail, premium = self._interpret(data)
            return DomainResult(
                domain=domain,
                status=status,
                detail=detail,
                premium=premium,
                raw={"status_code": 200, "rdap": data},
            )

        if resp.status_code in {429, 503}:
            return DomainResult(
                domain=domain,
                status="error",
                detail=f"RDAP rate limited or unavailable ({resp.status_code})",
                raw={"status_code": resp.status_code},
            )

        return DomainResult(
            domain=domain,
            status="unknown",
            detail=f"Unexpected RDAP status {resp.status_code}",
            raw={"status_code": resp.status_code},
        )

    def _interpret(self, data: dict[str, Any]) -> tuple[str, str, bool]:
        statuses = [str(s).lower() for s in (data.get("status") or [])]
        remarks = " ".join(
            " ".join(r.get("description") or [])
            if isinstance(r.get("description"), list)
            else str(r.get("description") or "")
            for r in (data.get("remarks") or [])
            if isinstance(r, dict)
        ).lower()

        premium = any("premium" in s for s in statuses) or "premium" in remarks
        if premium:
            return "premium", "RDAP indicates premium / restricted name", True

        if any("inactive" in s for s in statuses):
            return "available", "RDAP status inactive", False

        # Presence of registration entities / events ⇒ registered
        if data.get("entities") or data.get("events") or data.get("ldhName") or data.get("handle"):
            return "registered", "RDAP registration record found", False

        if statuses:
            return "registered", f"RDAP statuses: {', '.join(statuses)}", False

        return "unknown", "RDAP 200 without clear registration signals", False
