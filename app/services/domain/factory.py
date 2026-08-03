from __future__ import annotations

from app.config import get_settings
from app.services.domain.base import DomainProvider
from app.services.domain.rdap import RdapDomainProvider


def get_domain_provider() -> DomainProvider:
    """
    Select provider from DOMAIN_PROVIDER env.
    Future: godaddy / namecheap / etc. behind the same interface.
    """
    settings = get_settings()
    provider = (settings.domain_provider or "rdap").strip().lower()
    if provider in {"rdap", "whois", ""}:
        return RdapDomainProvider()
    # Optional registrar APIs can be wired here when DOMAIN_API_KEY is set.
    # For now fall back to RDAP so missing credentials never break the tool.
    return RdapDomainProvider()
