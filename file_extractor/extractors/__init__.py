"""Extractors package. The canonical registry lives in registry.py."""
from extractors.base import Extractor
from extractors.registry import get_extractors

# Backwards-compat: some callers import EXTRACTORS directly.
EXTRACTORS: list[Extractor] = get_extractors()
