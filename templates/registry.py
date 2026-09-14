"""Template registry."""

import logging
from typing import Dict, List, Optional, Tuple

from templates.metadata import TemplateMetadata
from templates.exceptions import (
    TemplateNotFoundError,
    TemplateIncompatibleError,
    TemplateUnavailableError,
)

logger = logging.getLogger(__name__)


class TemplateRegistry:
    def __init__(self):
        self._templates: Dict[str, TemplateMetadata] = {}

    def register(self, metadata: TemplateMetadata) -> None:
        self._templates[metadata.template_id] = metadata
        logger.info("Registered template '%s'", metadata.template_id)

    def register_from_inventory(self, inventory: List[Dict[str, Any]]) -> None:
        for item in inventory:
            metadata = TemplateMetadata(
                template_id=item.get("template_id", ""),
                name=item.get("name", ""),
                format=item.get("format", ""),
                aspect_ratio=item.get("aspect_ratio", ""),
                adapter_id=item.get("adapter_id", ""),
                available=item.get("available", False),
                source_path=item.get("source_path"),
                supported_content_types=tuple(item.get("supported_content_types", ())),
                supported_dynamic_fields=tuple(item.get("supported_dynamic_fields", ())),
                extra=item.get("extra", {}),
            )
            self.register(metadata)

    def lookup(self, template_id: str) -> TemplateMetadata:
        if template_id not in self._templates:
            raise TemplateNotFoundError(f"Template '{template_id}' not found in registry")
        return self._templates[template_id]

    def list_all(self) -> List[TemplateMetadata]:
        return list(self._templates.values())

    def list_available(self) -> List[TemplateMetadata]:
        return [t for t in self._templates.values() if t.available]

    def filter_by_format(self, content_format: str) -> List[TemplateMetadata]:
        return [t for t in self._templates.values() if t.format == content_format]

    def filter_by_aspect(self, aspect_ratio: str) -> List[TemplateMetadata]:
        return [t for t in self._templates.values() if t.aspect_ratio == aspect_ratio]

    def filter_by_adapter(self, adapter_id: str) -> List[TemplateMetadata]:
        return [t for t in self._templates.values() if t.adapter_id == adapter_id]

    def select(
        self,
        platform: str,
        aspect_ratio: str,
        content_format: str = "",
    ) -> TemplateMetadata:
        candidates = self._templates.values()

        if content_format:
            candidates = [t for t in candidates if t.format == content_format]
        if platform:
            candidates = [t for t in candidates if t.format == platform or content_format == platform]
        candidates = [t for t in candidates if t.aspect_ratio == aspect_ratio]

        available = [t for t in candidates if t.available]
        if available:
            return available[0]

        unavailable = [t for t in candidates if not t.available]
        if unavailable:
            raise TemplateUnavailableError(
                f"No available template for platform={platform}, aspect={aspect_ratio}, "
                f"format={content_format}. Found {len(unavailable)} unavailable template(s)."
            )

        raise TemplateIncompatibleError(
            f"No compatible template for platform={platform}, aspect={aspect_ratio}, "
            f"format={content_format}"
        )

    def validate_compatibility(
        self,
        template_id: str,
        content_format: str,
        aspect_ratio: str,
    ) -> Dict[str, bool]:
        tmpl = self.lookup(template_id)
        return {
            "format_match": tmpl.is_compatible_format(content_format),
            "aspect_match": tmpl.is_compatible_aspect(aspect_ratio),
            "available": tmpl.available,
            "compatible": (
                tmpl.is_compatible_format(content_format)
                and tmpl.is_compatible_aspect(aspect_ratio)
            ),
        }

    def get_template_ids(self) -> List[str]:
        return list(self._templates.keys())
