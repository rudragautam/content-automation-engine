"""Template-specific adapter.

Maps common content → template-specific data structures.
Generates JS data code for template population.
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple


class TemplateAdapter:
    def __init__(self, template_id: str, config: Dict[str, Any]):
        self.template_id = template_id
        self.data_var = config.get("data_var", "")
        self.data_source = config.get("data_source", "scenes")
        self.field_map = config.get("field_map", {})
        self.asset_field = config.get("asset_field", None)
        self.theme_vars = config.get("theme_vars", ())
        self.supported_dynamic_fields = config.get("supported_dynamic_fields", ())

    def get_data_variable(self) -> str:
        return self.data_var

    def get_theme_vars(self) -> Tuple[str, ...]:
        return self.theme_vars

    def get_supported_fields(self) -> Tuple[str, ...]:
        return self.supported_dynamic_fields

    def get_scene_items(self, content: Dict[str, Any]) -> List[Dict[str, Any]]:
        source_key = self.data_source
        scenes = content.get(source_key, content.get("scenes", content.get("chapters", content.get("slides", []))))
        items = []
        for scene in scenes:
            item = {}
            for data_field, content_field in self.field_map.items():
                if isinstance(scene, dict):
                    value = self._resolve_field(scene, content_field)
                else:
                    value = self._resolve_attr(scene, content_field)
                item[data_field] = value if value is not None else ""
            if self.asset_field and isinstance(scene, dict):
                asset = scene.get(self.asset_field)
                if asset:
                    item[self.asset_field] = asset
            items.append(item)
        return items

    def _resolve_field(self, scene: Dict[str, Any], field: str) -> Any:
        parts = field.split(".")
        current = scene
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
            if current is None:
                return None
        return current

    def _resolve_attr(self, obj, field: str) -> Any:
        if isinstance(obj, dict):
            return self._resolve_field(obj, field)
        parts = field.split(".")
        current = obj
        for part in parts:
            if hasattr(current, part):
                current = getattr(current, part)
            else:
                return None
            if current is None:
                return None
        return current

    def generate_data_code(self, content: Dict[str, Any]) -> str:
        items = self.get_scene_items(content)
        json_str = json.dumps(items, ensure_ascii=False, indent=2)
        return f"const {self.data_var} = {json_str};"

    def populate_data(self, html: str, content: Dict[str, Any]) -> str:
        data_code = self.generate_data_code(content)
        patterns = [
            rf"const\s+{re.escape(self.data_var)}\s*=\s*\[.*?\]\s*;",
            rf"const\s+{re.escape(self.data_var)}\s*=\s*\[.*?\]",
            rf"let\s+{re.escape(self.data_var)}\s*=\s*\[.*?\]",
            rf"var\s+{re.escape(self.data_var)}\s*=\s*\[.*?\]",
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                start = match.start()
                end = match.end()
                if html[end:end+1] == ";":
                    end += 1
                return html[:start] + data_code + "\n" + html[end:]
        return html

    def populate_theme(self, html: str, theme: Dict[str, str]) -> str:
        if not theme:
            return html
        for var_name, value in theme.items():
            css_var = f"--{var_name}"
            pattern = "(" + re.escape(css_var) + r":\s*)[^;]+(;|\})"
            replacement = "\\1" + value + "\\2"
            html = re.sub(pattern, replacement, html)
        return html

    def populate_assets(self, html: str, assets: Dict[str, str]) -> str:
        if not assets:
            return html
        for key, path in assets.items():
            escaped_key = re.escape(key)
            patterns = [
                r"url\s*\(\s*['\"]?" + escaped_key + r"['\"]?\s*\)",
                r"url\s*\(\s*['\"]?\{\{\s*asset\s*:\s*" + escaped_key + r"\s*\}\}\s*\)",
            ]
            for pattern in patterns:
                html = re.sub(pattern, "url('" + path + "')", html)
            html = html.replace("{{asset:" + key + "}}", path)
        return html

    def populate(
        self,
        html: str,
        content: Dict[str, Any],
        assets: Dict[str, str] = None,
        theme: Dict[str, str] = None,
    ) -> str:
        html = self.populate_data(html, content)
        if assets:
            html = self.populate_assets(html, assets)
        if theme:
            html = self.populate_theme(html, theme)
        return html
