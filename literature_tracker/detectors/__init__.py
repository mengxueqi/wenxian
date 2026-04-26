"""Detection stage: identify new papers, updates, errata, and retractions."""

from .changes import build_change_candidates

__all__ = ["build_change_candidates"]
