"""Template adapter - maps common content to template-specific data structures."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class TemplateMapping:
    content_field: str
    template_field: str
    transform: Optional[str] = None


class TemplateAdapter:
    def __init__(self, adapter_id: str, mappings: Dict[str, Tuple[str, str]] = None):
        self.adapter_id = adapter_id
        self._mappings = mappings or {}

    def map_content(self, content: Dict[str, Any]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for common_field, template_field in self._mappings.items():
            if common_field in content:
                result[template_field] = content[common_field]
            else:
                result[template_field] = ""
        return result

    def map_asset(self, asset: Dict[str, Any], role: str = "background") -> Dict[str, Any]:
        return {
            "asset_id": asset.get("asset_id", ""),
            "path": asset.get("path", ""),
            "role": role,
            "type": asset.get("type", "image"),
        }

    def map_theme(self, theme: Dict[str, Any], supported_fields: Tuple[str, ...] = ()) -> Dict[str, Any]:
        if not supported_fields:
            return {}
        return {k: v for k, v in theme.items() if k in supported_fields}
