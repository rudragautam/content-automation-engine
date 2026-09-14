"""Populated HTML output generator."""

import os
import logging
from typing import Any, Dict, Optional

from templates.loader import TemplateLoader
from templates.adapters.base import TemplateAdapter
from templates.adapters.registry import TemplateAdapterRegistry
from templates.registry import TemplateRegistry
from templates.exceptions import TemplateNotFoundError, TemplateUnavailableError

logger = logging.getLogger(__name__)


class TemplatePopulator:
    def __init__(
        self,
        adapter_registry: TemplateAdapterRegistry = None,
        template_registry: TemplateRegistry = None,
        output_dir: str = "output/populated",
    ):
        self.loader = TemplateLoader()
        self.adapter_registry = adapter_registry or TemplateAdapterRegistry()
        self.template_registry = template_registry
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def populate(
        self,
        template_id: str,
        content: Dict[str, Any],
        assets: Dict[str, str] = None,
        theme: Dict[str, str] = None,
    ) -> str:
        try:
            html, metadata = self.loader.load(template_id)
        except (TemplateNotFoundError, TemplateUnavailableError):
            return self._build_placeholder(template_id, content)

        try:
            adapter = self.adapter_registry.get_adapter(template_id)
        except KeyError:
            return self._build_placeholder(template_id, content)
        html = adapter.populate(html, content, assets=assets, theme=theme)
        return html

    def populate_and_save(
        self,
        template_id: str,
        content: Dict[str, Any],
        assets: Dict[str, str] = None,
        theme: Dict[str, str] = None,
    ) -> str:
        html = self.populate(template_id, content, assets=assets, theme=theme)
        filename = f"{template_id}_populated.html"
        output_path = os.path.join(self.output_dir, filename)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info("Saved populated template: %s", output_path)
        return output_path

    def get_original_template(self, template_id: str) -> str:
        html, _ = self.loader.load(template_id)
        return html

    def _build_placeholder(self, template_id: str, content: Dict[str, Any]) -> str:
        title = content.get("topic", content.get("title", "Content")) if content else "Content"
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{template_id}</title>
</head>
<body>
<h1>{title}</h1>
<p>Template '{template_id}' is unavailable or incomplete.</p>
</body>
</html>"""
