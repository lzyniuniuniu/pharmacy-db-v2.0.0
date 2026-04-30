"""Registry of available extractors.

When you add a new document type, register its extractor here.
The dispatcher iterates this list to find one that handles a given PDF.

Order matters: more-specific extractors should come first if there's
any chance of overlap.
"""
from .base import Extractor
from .inspection import InspectionExtractor


def get_extractors() -> list[Extractor]:
    """Return the list of registered extractor instances."""
    return [
        InspectionExtractor(),
        # Future:
        # SOPExtractor(),
        # ActionReportExtractor(),
    ]