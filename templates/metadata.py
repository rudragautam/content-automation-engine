"""Template metadata."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class TemplateMetadata:
    template_id: str
    name: str
    format: str
    aspect_ratio: str
    supported_content_types: Tuple[str, ...] = ()
    supported_dynamic_fields: Tuple[str, ...] = ()
    adapter_id: str = ""
    available: bool = False
    source_path: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def is_compatible_format(self, content_format: str) -> bool:
        return content_format in self.supported_content_types or not self.supported_content_types

    def is_compatible_aspect(self, aspect_ratio: str) -> bool:
        return self.aspect_ratio == aspect_ratio
