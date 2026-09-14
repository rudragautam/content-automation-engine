"""Template loader - safely loads existing HTML files."""

import logging
import os
from typing import Optional

from templates.metadata import TemplateMetadata
from templates.exceptions import TemplateNotFoundError, TemplateUnavailableError

logger = logging.getLogger(__name__)


class TemplateLoader:
    def __init__(self, templates_dir: str = "templates"):
        self.templates_dir = templates_dir

    def load(self, template_id: str, source_path: Optional[str] = None) -> Tuple[str, TemplateMetadata]:
        if source_path is None:
            source_path = os.path.join(self.templates_dir, f"{template_id}.html")

        if not os.path.isfile(source_path):
            raise TemplateUnavailableError(
                f"Template '{template_id}' source file not found at: {source_path}. "
                "The template has been registered but its HTML source has not been supplied yet."
            )

        try:
            with open(source_path, "r", encoding="utf-8") as f:
                html_content = f.read()
        except Exception as e:
            raise TemplateNotFoundError(f"Failed to load template '{template_id}': {e}")

        if not html_content.strip():
            raise TemplateUnavailableError(
                f"Template '{template_id}' source file is empty."
            )

        metadata = TemplateMetadata(
            template_id=template_id,
            name=template_id,
            format="",
            aspect_ratio="",
            adapter_id="",
            available=True,
            source_path=source_path,
        )

        logger.info("Loaded template '%s' from %s", template_id, source_path)
        return html_content, metadata

    def exists(self, template_id: str, source_path: Optional[str] = None) -> bool:
        if source_path is None:
            source_path = os.path.join(self.templates_dir, f"{template_id}.html")
        return os.path.isfile(source_path)

    def validate(self, template_id: str, source_path: Optional[str] = None) -> bool:
        try:
            self.load(template_id, source_path)
            return True
        except (TemplateNotFoundError, TemplateUnavailableError):
            return False
