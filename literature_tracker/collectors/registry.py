from __future__ import annotations

from ..models import SourceConfig
from .base import BaseCollector, CollectorError
from .cip import CIPCollector
from .generic import GenericJournalCollector
from .springer import SpringerCollector


def get_collector(source: SourceConfig) -> BaseCollector:
    generic_collector = GenericJournalCollector()
    collectors: dict[str, BaseCollector] = {
        "asm": generic_collector,
        "cell": generic_collector,
        "microbiology_research": generic_collector,
        "magtech_cip": CIPCollector(),
        "nature": generic_collector,
        "oup": generic_collector,
        "scientific_american": generic_collector,
        "sciencedirect": generic_collector,
        "springer": SpringerCollector(),
        "wiley": generic_collector,
    }
    try:
        return collectors[source.platform]
    except KeyError as exc:
        raise CollectorError(f"Unsupported platform: {source.platform}") from exc
