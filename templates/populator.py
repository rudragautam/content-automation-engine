"""Template populator - populates dynamic values into templates."""

import logging
from typing import Any, Dict, Optional, Tuple

from templates.exceptions import TemplateAdapterError

logger = logging.getLogger(__name__)


class TemplatePopulator:
    def __init__(self):
        self._data_markers = ("{{", "}}")

    def populate(
        self,
        html_content: str,
        data: Dict[str, Any],
        assets: Dict[str, Any] = None,
        theme: Dict[str, Any] = None,
    ) -> str:
        result = html_content
        result = self._populate_data_markers(result, data)
        result = self._populate_asset_refs(result, assets or {})
        result = self._populate_theme(result, theme or {})
        return result

    def _populate_data_markers(self, html: str, data: Dict[str, Any]) -> str:
        result = html
        for key, value in data.items():
            marker = f"{{{{{{{key}}}}}}}"
            replacement = str(value) if value is not None else ""
            result = result.replace(marker, replacement)
            alt_marker = f"{{{{{key}}}}}"
            result = result.replace(alt_marker, replacement)
        return result

    def _populate_asset_refs(self, html: str, assets: Dict[str, Any]) -> str:
        result = html
        for asset_key, asset_value in assets.items():
            marker = f"{{{{asset:{asset_key}}}}}"
            replacement = str(asset_value) if asset_value is not None else ""
            result = result.replace(marker, replacement)
        return result

    def _populate_theme(self, html: str, theme: Dict[str, Any]) -> str:
        result = html
        for key, value in theme.items():
            marker = f"{{{{theme:{key}}}}}"
            replacement = str(value) if value is not None else ""
            result = result.replace(marker, replacement)
        return result
