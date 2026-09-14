"""End-to-end orchestration for the content automation engine."""

import json
import os
import uuid
import logging
from typing import Any, Dict, List, Optional, Tuple

from core.run_config import RunConfig
from core.manifest import Manifest
from core.content_mode import ContentMode, build_content_from_brief
from core.briefing import ContentBrief
from core.claims import Claim, CheckedClaim
from templates.loader import TemplateLoader
from templates.registry import TemplateRegistry
from templates.adapters.registry import TemplateAdapterRegistry
from templates.exceptions import (
    TemplateNotFoundError,
    TemplateUnavailableError,
    TemplateIncompatibleError,
)
from media.asset import Asset
from media.validation import AssetValidator

logger = logging.getLogger(__name__)


class EngineOrchestrator:
    def __init__(
        self,
        config: RunConfig,
        template_registry: TemplateRegistry = None,
        adapter_registry: TemplateAdapterRegistry = None,
    ):
        self.config = config
        self.run_id = str(uuid.uuid4())[:12]
        self.template_registry = template_registry or TemplateRegistry()
        self.adapter_registry = adapter_registry or TemplateAdapterRegistry()
        self.asset_validator = AssetValidator()
        self.errors: List[str] = []

    def run(self) -> Dict[str, Any]:
        self.errors = []
        validation_errors = self.config.validate()
        if validation_errors:
            self.errors.extend(validation_errors)
            return self._error_result("configuration", "; ".join(validation_errors))

        content_data: Dict[str, Any] = {}
        factual_claims: List = []
        source_references: List[str] = []

        try:
            if self.config.mode == ContentMode.AUTO:
                content_data, factual_claims, source_references = self._run_auto()
            elif self.config.mode == ContentMode.CUSTOM:
                content_data, factual_claims, source_references = self._run_custom()
            elif self.config.mode == ContentMode.HYBRID:
                content_data, factual_claims, source_references = self._run_hybrid()
            else:
                self.errors.append(f"unsupported mode: {self.config.mode}")
                return self._error_result("mode", f"unsupported mode: {self.config.mode}")
        except Exception as e:
            self.errors.append(str(e))
            return self._error_result("execution", str(e))

        template_html = ""
        template_id = ""
        try:
            template_html, template_id = self._select_and_populate_template(content_data)
        except (TemplateNotFoundError, TemplateUnavailableError, TemplateIncompatibleError) as e:
            self.errors.append(str(e))
            return self._error_result("template", str(e))
        except Exception as e:
            self.errors.append(str(e))
            return self._error_result("template", str(e))

        output_dir = self._prepare_output_dir()
        populated_path = os.path.join(output_dir, "populated.html")
        self._write_file(populated_path, template_html)

        content_json_path = os.path.join(output_dir, "content.json")
        content_payload = {
            "run_id": self.run_id,
            "topic": self.config.topic,
            "storyline": list(self.config.storyline),
            "key_points": list(self.config.key_points),
            "mode": self.config.mode.value if hasattr(self.config.mode, "value") else str(self.config.mode),
            "content_format": self.config.content_format,
            "platform": self.config.platform,
            "aspect_ratio": self.config.aspect_ratio,
            "content": content_data,
            "factual_claims": [
                {"text": c.text, "classification": c.classification}
                if isinstance(c, (Claim, CheckedClaim))
                else str(c)
                for c in (factual_claims or [])
            ],
            "source_references": list(source_references),
        }
        self._write_file(content_json_path, json.dumps(content_payload, indent=2, default=str))

        assets_path = os.path.join(output_dir, "assets.json")
        assets_payload = {}
        for asset_id, asset_path in (self.config.assets or {}).items():
            asset = Asset(asset_id=asset_id, path=asset_path, type="image")
            validation = self.asset_validator.validate(asset)
            assets_payload[asset_id] = {
                "path": asset_path,
                "type": "image",
                "valid": validation.valid,
                "errors": list(validation.errors),
                "warnings": list(validation.warnings),
            }
        self._write_file(assets_path, json.dumps(assets_payload, indent=2))

        manifest = Manifest.from_run_result(
            run_id=self.run_id,
            config=self.config,
            output_path=populated_path,
            content={
                "topic": self.config.topic,
                "source_references": source_references,
                "factual_claims": factual_claims or [],
            },
        )
        manifest_path = os.path.join(output_dir, "manifest.json")
        self._write_file(manifest_path, manifest.to_json())

        return {
            "run_id": self.run_id,
            "output_dir": output_dir,
            "populated_html": populated_path,
            "manifest": manifest_path,
            "content": content_json_path,
            "assets": assets_path,
            "template_id": template_id,
            "errors": self.errors,
            "success": len(self.errors) == 0,
        }

    def _prepare_output_dir(self) -> str:
        run_dir = os.path.join(self.config.output_dir, self.run_id)
        os.makedirs(run_dir, exist_ok=True)
        return run_dir

    def _write_file(self, path: str, content: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("Wrote %s (%d bytes)", path, len(content))

    def _run_auto(self) -> Tuple[Dict[str, Any], List, List[str]]:
        brief = ContentBrief(
            topic=self.config.topic,
            audience="general",
            platform=self.config.platform,
            format=self.config.content_format,
            angle="informative",
            key_points=self.config.key_points,
            cta=None,
        )
        content_dict = build_content_from_brief(brief, ContentMode.AUTO)
        return content_dict, [], []

    def _run_custom(self) -> Tuple[Dict[str, Any], List, List[str]]:
        brief = ContentBrief(
            topic=self.config.topic,
            audience="general",
            platform=self.config.platform,
            format=self.config.content_format,
            angle="informative",
            key_points=self.config.key_points,
            cta=None,
        )
        content_dict = build_content_from_brief(
            brief,
            ContentMode.CUSTOM,
            custom_key_points=self.config.key_points or (),
            custom_storyline=" ".join(self.config.storyline) if self.config.storyline else "",
        )
        if not content_dict.get("key_points") and self.config.storyline:
            content_dict["key_points"] = list(self.config.storyline)
        return content_dict, [], []

    def _run_hybrid(self) -> Tuple[Dict[str, Any], List, List[str]]:
        brief = ContentBrief(
            topic=self.config.topic,
            audience="general",
            platform=self.config.platform,
            format=self.config.content_format,
            angle="informative",
            key_points=self.config.key_points,
            cta=None,
        )
        storyline_text = " ".join(self.config.storyline) if self.config.storyline else ""
        hybrid_points = list(self.config.key_points)
        if storyline_text:
            lines = [l.strip() for l in storyline_text.split("\n") if l.strip()]
            hybrid_points.extend(lines[:10])
        hybrid_points = tuple(dict.fromkeys(hybrid_points))
        content_dict = build_content_from_brief(
            brief,
            ContentMode.HYBRID,
            custom_key_points=hybrid_points,
            custom_storyline=storyline_text,
        )
        return content_dict, [], []

    def _select_template(self) -> Tuple[str, str]:
        config = self.config
        template_id = None
        if config.template_id:
            template_id = config.template_id
            if template_id.endswith(".html"):
                template_id = template_id[:-5]

        if template_id:
            try:
                meta = self.template_registry.lookup(template_id)
                if not meta.available:
                    raise TemplateUnavailableError(f"Template '{template_id}' is not available")
            except TemplateNotFoundError:
                pass
            loader = TemplateLoader()
            if loader.exists(template_id):
                html, _ = loader.load(template_id)
                return template_id, html
            raise TemplateNotFoundError(f"Template '{template_id}' not found")

        if config.template_filename and config.template_filename.endswith(".html"):
            template_id = config.template_filename[:-5]
            loader = TemplateLoader()
            if loader.exists(template_id):
                html, _ = loader.load(template_id)
                return template_id, html

        try:
            meta = self.template_registry.select(
                platform=self.config.platform,
                aspect_ratio=self.config.get_aspect_from_platform(),
                content_format=self.config.content_format,
            )
            template_id = meta.template_id
            loader = TemplateLoader()
            html, _ = loader.load(template_id)
            return template_id, html
        except (TemplateUnavailableError, TemplateIncompatibleError):
            raise
        except Exception as e:
            raise TemplateNotFoundError(f"No template found: {e}")

    def _select_and_populate_template(self, content_data: Dict[str, Any]) -> Tuple[str, str]:
        template_id, html = self._select_template()

        adapter = None
        try:
            adapter = self.adapter_registry.get_adapter(template_id)
        except KeyError:
            pass

        if adapter is not None:
            scenes = content_data.get("scenes", content_data.get("key_points", []))
            if isinstance(scenes, tuple):
                scenes = list(scenes)
            if isinstance(scenes, list):
                scene_dicts = []
                for sp in scenes:
                    if isinstance(sp, dict):
                        scene_dicts.append(sp)
                    else:
                        scene_dicts.append({"title": str(sp), "text": ""})
                if not scene_dicts:
                    scene_dicts = [{"title": self.config.topic, "text": ""}]
                content = {"scenes": scene_dicts}
            else:
                content = {"scenes": [{"title": self.config.topic, "text": ""}]}
            populated = adapter.populate(
                html,
                content,
                assets=self.config.assets or None,
                theme=self.config.theme or None,
            )
            return populated, template_id

        from templates.populator import TemplatePopulator
        populator = TemplatePopulator()
        data = {
            "title": self.config.topic,
            "hook": content_data.get("hook", ""),
            "body": content_data.get("body", ""),
            "topic": self.config.topic,
        }
        populated = populator.populate(
            html,
            data,
            assets=self.config.assets or None,
            theme=self.config.theme or None,
        )
        return populated, template_id

    def _error_result(self, error_type: str, message: str) -> Dict[str, Any]:
        output_dir = self._prepare_output_dir()
        manifest = Manifest(
            run_id=self.run_id,
            timestamp="",
            mode=self.config.mode.value if hasattr(self.config.mode, "value") else str(self.config.mode),
            content_format=self.config.content_format,
            platform=self.config.platform,
            aspect_ratio=self.config.aspect_ratio,
            template_id=self.config.template_id or "",
            template_filename=self.config.template_filename or "",
            topic=self.config.topic,
            assets={},
            theme={},
            output_path=output_dir,
            error=message,
        )
        manifest_path = os.path.join(output_dir, "manifest.json")
        self._write_file(manifest_path, manifest.to_json())
        return {
            "run_id": self.run_id,
            "output_dir": output_dir,
            "error": message,
            "errors": self.errors,
            "success": False,
        }
