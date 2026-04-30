# ACP Case Summary Extractor

Extracts structured data from Alberta College of Pharmacy case summary PDFs into a canonical JSON
format suitable for loading into the inspection database

## Quick start

```bash
# extract one PDF:
python extract_case_summary.py path/to/report.pdf --output report.json --pretty

# pie to stdout:
python extract_case_summary.py path/to/report.pdf --pretty
```

## What it does

Given an ACP case summary PDF, produces a JSON document containing:

- **Source document**: file hash, name, page count, generation timestamp
- **Pharmacy**: name and license number (when present)
- **Case**: case number, type, state, licensee, consultant
- **Assessments**: One per visit date, each containing
  - **Findings**: identified date, due date, compelted date, state, person responsible, category (parent+ child), verbatim description, extracted URLs, regulatory references, source page numbers

Every record traces back to the source page. Verbatim text is preserved exactly - no LLM summarization at this stage.

## Validation

Each extraction returns a `validation_status`:

- **passed**: all expected fields populatedm, all findings well-formed.
- **passed_with_warnings**: extracted successfully, but some optional fields are missing (e.g., pharmcy/consultant name absent - may from someone's assignment)
- **failed**: a hard requirement was violated (no case number, no findings). CLI exits with code 2.

Warnings are listed in `extraction_metadata.validation_warnings` and are intended as queue for human review.

## When to reach for the source code

Situations which need edition on the code:

1. **A PDF with a different layout**: the `COLUMNS` constant near the top defines x-coordinate ranges. Inspect a problem PDF with `pdfpumber.extract_words()`, compare to the constants, adjust if needed.
2. **A new metadata field**: add a regex to `CASE_META_PATTERNS` and a field to the 'Case' or 'Pharmacy' dataclass. Update `extract_case_metadata` to populate it.

The file is organized in clearly labeled sections (Constants, Data Classes, Utilities, Columnar Parsing, Case Metadata, Assembly, Validation, CLI).

## Known design descisions

- **No database here**: This script is a pure extractor.
- **No LLM summarization here**: `description_summary` and `summary_bullets` are always null. Add them in a downstream step.
- **No anonymization here**: this populates the *private* database only. The library/public version is a separate downstream pipeline.
- **Document-wide extraction**: findings whose descriptions span page
  boundaries are captured in one piece.


## Output schema (abbreviated)

```json
{
  "extraction_metadata": {
    "extractor_version": "0.1.0",
    "extracted_at": "2026-04-25T11:36:23+00:00",
    "extraction_method": "pdfplumber_columnar",
    "validation_status": "passed",
    "validation_warnings": [],
    "validation_errors": []
  },
  "source_document": {
    "file_hash": "sha256:...",
    "file_name": "...pdf",
    "page_count": 11,
    "report_generated_at": "2025-06-18T17:57:00"
  },
  "regulatory_body": {"name": "Alberta College of Pharmacy", "short_name": "ACP"},
  "pharmacy": {"name": "...", "license_number": "..."},
  "case": {
    "case_number": "PP0002449",
    "case_type": "Routine",
    "case_state": "Work in Progress",
    "case_closed_date": null,
    "licensee": {"name": "...", "email": "..."},
    "consultant": {"name": "...", "email": "...", "role": "..."},
    "consultant_assignment_status": "confirmed"
  },
  "assessments": [
    {
      "ordinal": 1,
      "assessment_date": "2025-03-19",
      "findings": [
        {
          "ordinal": 1,
          "identified_date": "2025-03-19",
          "due_date": "2025-04-19",
          "completed_date": "2025-04-08",
          "state": "Closed",
          "person_responsible": "Rebecca Perrin",
          "category": {
            "raw": "Operations : Injections",
            "parent": "Operations",
            "child": "Injections"
          },
          "description_verbatim": "...",
          "description_summary": null,
          "summary_bullets": null,
          "referenced_standards": [...],
          "referenced_urls": [...],
          "source_page_numbers": [2]
        }
      ]
    }
  ]
}
```


## Tested on
 
Three real ACP case summary PDFs:
- A standard "Routine" case with full metadata (Beaverlodge, 27 findings, 2 visits)
- A "Routine" case with a multi-pharmacy ownership transition (Castle Downs, 17 findings, 3 visits)
- A "Sterile compounding" case with NO header metadata (SCL/Galvin, 41 findings, 2 visits)