"""Asset validation."""

import os
import logging
from typing import List

from media.asset import Asset, ValidationResult

logger = logging.getLogger(__name__)


SUPPORTED_ASSET_TYPES = (
    "image",
    "video",
    "screenshot",
    "logo",
    "chart",
    "reference_media",
)

SAFE_PATH_PREFIXES = ("/", "./", "../", "assets/", "media/", "images/", "static/")


class AssetValidator:
    def __init__(self, base_dir: str = ""):
        self.base_dir = base_dir

    def validate(self, asset: Asset) -> ValidationResult:
        errors: List[str] = []
        warnings: List[str] = []

        if not asset.asset_id:
            errors.append("asset_id is required")

        if not asset.path:
            errors.append("path is required")

        if asset.type not in SUPPORTED_ASSET_TYPES:
            errors.append(
                f"unsupported asset type: '{asset.type}'. "
                f"Supported: {SUPPORTED_ASSET_TYPES}"
            )

        if asset.path and not self._is_safe_path(asset.path):
            errors.append(f"unsafe path: '{asset.path}'")

        if asset.path and not self._file_exists(asset.path):
            warnings.append(f"file does not exist: '{asset.path}'")

        if asset.assigned_to and not self._is_valid_assignment(asset.assigned_to):
            warnings.append(f"unusual assignment target: '{asset.assigned_to}'")

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def _is_safe_path(self, path: str) -> bool:
        if path.startswith(("http://", "https://", "ftp://")):
            return False
        if path.startswith(SAFE_PATH_PREFIXES) or path.startswith("."):
            return True
        return False

    def _file_exists(self, path: str) -> bool:
        check_path = path
        if self.base_dir and not os.path.isabs(path):
            check_path = os.path.join(self.base_dir, path)
        return os.path.isfile(check_path)

    def _is_valid_assignment(self, assignment: str) -> bool:
        valid_targets = (
            "scene",
            "scenes",
            "slide",
            "slides",
            "section",
            "sections",
            "cover",
            "slot",
            "slots",
        )
        return assignment.lower() in valid_targets
