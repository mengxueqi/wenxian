from .base import BaseCollector, CollectorError
from .cip import CIPCollector
from .generic import GenericJournalCollector
from .registry import get_collector
from .springer import SpringerCollector

__all__ = [
    "BaseCollector",
    "CIPCollector",
    "CollectorError",
    "GenericJournalCollector",
    "SpringerCollector",
    "get_collector",
]
