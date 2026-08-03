from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DomainResult:
    domain: str
    status: str  # available | registered | unknown | error | premium | aftermarket
    detail: str = ""
    premium: bool = False
    cached: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "status": self.status,
            "detail": self.detail,
            "premium": self.premium,
            "cached": self.cached,
        }


class DomainProvider(ABC):
    """Swap RDAP / registrar APIs behind this interface."""

    @abstractmethod
    async def check_domain(self, domain: str) -> DomainResult:
        raise NotImplementedError
