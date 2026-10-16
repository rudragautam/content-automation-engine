"""Per-niche Excel content templates: download, fill (by hand or with AI), upload."""

from content_templates.excel import ImportResult, build_prompt, build_workbook, read_workbook, workbook_bytes
from content_templates.specs import NICHES, NicheSpec, get_spec

__all__ = [
    "ImportResult", "NICHES", "NicheSpec", "build_prompt", "build_workbook",
    "get_spec", "read_workbook", "workbook_bytes",
]
