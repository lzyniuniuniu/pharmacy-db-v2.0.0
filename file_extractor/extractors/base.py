"""Base class for document extractors.

Each extractor handles one document type. The dispatcher uses
`can_handle()` to figure out which extractor to apply to a given PDF.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pdfplumber.pdf import PDF as PdfPlumberPDF


class Extractor(ABC):
    """Abstract base class for all document extractors.

    Subclasses must:
    - Set DOCUMENT_TYPE to a string identifier (e.g., "case_summary", "sop")
    - Implement can_handle(pdf) to detect their document type
    - Implement extract(path) to parse the PDF into a canonical dict
    """

    # Subclasses override this. Used by the loader to know what kind of
    # data the extracted JSON represents.
    DOCUMENT_TYPE: str = "unknown"

    @abstractmethod
    def can_handle(self, pdf: PdfPlumberPDF) -> bool:
        """Return True if this extractor recognizes the document.

        Should be cheap — usually inspecting the first page or two.
        Don't extract the full document just to decide.
        """
        ...

    @abstractmethod
    def extract(self, pdf_path: Path) -> dict[str, Any]:
        """Extract the document into the canonical JSON shape for this type.

        Each document type has its own JSON schema; extractors are
        responsible for producing the shape their downstream loader expects.
        """
        ...