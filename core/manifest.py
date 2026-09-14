"""Manifest/provenance generation for each run."""

import json
import os
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.run_config import RunConfig


@dataclass
class Manifest:
    run_id: str
    timestamp: str
    mode: str
    content_format: str
    platform: str
    aspect_ratio: str
    template_id: str
    template_filename: str
    topic: str
    assets: Dict[str, Any]
    theme: Dict[str, str]
    output_path: str
    source_references: List[str] = field(default_factory=list)
    factual_claims: List[str] = field(default_factory=list)
    content_mode: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "mode": self.mode,
            "content_format": self.content_format,
            "platform": self.platform,
            "aspect_ratio": self.aspect_ratio,
            "template_id": self.template_id,
            "template_filename": self.template_filename,
            "topic": self.topic,
            "assets": self.assets,
            "theme": self.theme,
            "output_path": self.output_path,
            "source_references": self.source_references,
            "factual_claims": self.factual_claims,
            "content_mode": self.content_mode,
            "error": self.error,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def save(self, output_dir: str) -> str:
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, "manifest.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())
        return path

    @classmethod
    def from_run_result(
        cls,
        run_id: str,
        config: RunConfig,
        output_path: str,
        content: Dict[str, Any] = None,
        error: Optional[str] = None,
    ) -> "Manifest":
        topic = config.topic
        if content:
            topic = content.get("topic", topic)
        asset_data = {}
        for asset_id, asset_path in (config.assets or {}).items():
            asset_data[asset_id] = {
                "path": asset_path,
                "validated": False,
            }
        return cls(
            run_id=run_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            mode=config.mode.value if hasattr(config.mode, "value") else str(config.mode),
            content_format=config.content_format,
            platform=config.platform,
            aspect_ratio=config.aspect_ratio,
            template_id=config.template_id or "",
            template_filename=config.template_filename or "",
            topic=topic,
            assets=asset_data,
            theme=config.theme or {},
            output_path=output_path,
            source_references=list(content.get("source_references", [])) if content else [],
            factual_claims=[
                claim.get("text", str(claim)) if isinstance(claim, dict) else str(claim)
                for claim in (content.get("factual_claims", []) if content else [])
            ],
            content_mode=config.mode.value if hasattr(config.mode, "value") else str(config.mode),
            error=error,
        )
