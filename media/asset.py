"""Asset metadata model."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


@dataclass
class ValidationResult:
    valid: bool
    errors: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Asset:
    asset_id: str
    path: str
    type: str
    source: Optional[str] = None
    attribution: Optional[str] = None
    description: Optional[str] = None
    dimensions: Optional[str] = None
    assigned_to: Optional[str] = None
    role: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_image(self) -> bool:
        return self.type in ("image", "screenshot", "logo", "chart", "reference_media")

    def is_video(self) -> bool:
        return self.type == "video"
