from __future__ import annotations

from ..models import SourceConfig
from .base import BaseCollector, CollectorError
from .cip import CIPCollector
from .springer import SpringerCollector


def get_collector(source: SourceConfig) -> BaseCollector:
    collectors: dict[str, BaseCollector] = {
        "magtech_cip": CIPCollector(),
        "springer": SpringerCollector(),
    }
    try:
        return collectors[source.platform]
    except KeyError as exc:
        raise CollectorError(f"Unsupported platform: {source.platform}") from exc

