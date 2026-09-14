"""CLI entry point for the content automation engine.

Usage:
    python engine.py --mode custom --topic "My Topic" --template 02_Geeta_Gyaan_9x16.html
    python engine.py --mode auto --topic "My Topic" --platform youtube_short
    python engine.py --mode hybrid --topic "My Topic" --storyline "Point 1" "Point 2"

No business logic here. CLI -> Orchestrator -> Existing modules.
"""

import argparse
import json
import logging
import os
import sys

from core.run_config import RunConfig
from core.content_mode import ContentMode
from core.orchestrator import EngineOrchestrator
from templates.registry import TemplateRegistry
from templates.adapters.registry import TemplateAdapterRegistry


def parse_args(args=None):
    parser = argparse.ArgumentParser(
        description="Content Automation Engine - end-to-end runner",
    )
    parser.add_argument(
        "--mode",
        choices=["auto", "custom", "hybrid"],
        default="custom",
        help="Execution mode (default: custom)",
    )
    parser.add_argument("--topic", default="", help="Content topic")
    parser.add_argument("--template", default="", help="Template ID or filename")
    parser.add_argument(
        "--platform",
        default="youtube_short",
        help="Platform: youtube_short, youtube_long, social_post, carousel",
    )
    parser.add_argument(
        "--format",
        default="short_video",
        help="Content format: short_video, long_video, post, carousel",
    )
    parser.add_argument("--aspect", default="9:16", help="Aspect ratio: 9:16, 16:9, 1:1")
    parser.add_argument(
        "--storyline",
        nargs="*",
        default=[],
        help="Storyline key points (CUSTOM/HYBRID mode)",
    )
    parser.add_argument(
        "--key-points",
        nargs="*",
        default=[],
        help="Key points (CUSTOM/HYBRID mode)",
    )
    parser.add_argument(
        "--asset",
        action="append",
        default=[],
        help="Asset as asset_id=path (repeatable)",
    )
    parser.add_argument(
        "--theme",
        action="append",
        default=[],
        help="Theme var as key=value (repeatable)",
    )
    parser.add_argument(
        "--output",
        default="output/runs",
        help="Output directory (default: output/runs)",
    )
    parser.add_argument(
        "--output-filename",
        default=None,
        help="Output filename (default: run_id/populated.html)",
    )
    parser.add_argument(
        "--run",
        default=None,
        help="Run ID for video generation from existing artifacts",
    )
    parser.add_argument(
        "--video",
        action="store_true",
        help="Generate video after run (requires FFmpeg + Playwright)",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=30,
        help="Video FPS (default: 30)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=5.0,
        help="Video duration in seconds (default: 5.0)",
    )
    parser.add_argument(
        "--scene-count",
        type=int,
        default=6,
        help="Number of scenes to capture (default: 6)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose logging",
    )
    return parser.parse_args(args)


def build_config(args) -> RunConfig:
    assets = {}
    for item in args.asset:
        if "=" in item:
            key, path = item.split("=", 1)
            assets[key] = path

    theme = {}
    for item in args.theme:
        if "=" in item:
            key, value = item.split("=", 1)
            theme[key] = value

    storyline = tuple(args.storyline) if args.storyline else ()
    key_points = tuple(args.key_points) if args.key_points else ()

    template_id = args.template or None
    template_filename = None
    if template_id and template_id.endswith(".html"):
        template_filename = template_id
        template_id = template_id[:-5]

    return RunConfig(
        mode=ContentMode(args.mode.upper()),
        topic=args.topic,
        storyline=storyline,
        key_points=key_points,
        platform=args.platform,
        content_format=args.format,
        aspect_ratio=args.aspect,
        template_id=template_id,
        template_filename=template_filename,
        assets=assets,
        theme=theme,
        output_dir=args.output,
        output_filename=args.output_filename,
    )


def main(args=None):
    parsed = parse_args(args)
    if parsed.verbose:
        logging.basicConfig(level=logging.INFO)
    else:
        logging.basicConfig(level=logging.WARNING)

    if parsed.run:
        run_dir = os.path.join(parsed.output, parsed.run)
        if not os.path.isdir(run_dir):
            print(json.dumps({"success": False, "error": f"Run {parsed.run} not found"}))
            sys.exit(1)
        from core.video_orchestrator import VideoOrchestrator
        vor = VideoOrchestrator(
            run_dir=run_dir,
            fps=parsed.fps,
            duration=parsed.duration,
            scene_count=parsed.scene_count,
        )
        result = vor.run()
        print(json.dumps(result, indent=2, default=str))
        sys.exit(0 if result.get("success") else 1)

    config = build_config(parsed)
    registry = TemplateRegistry()
    adapters = TemplateAdapterRegistry()

    orchestrator = EngineOrchestrator(
        config=config,
        template_registry=registry,
        adapter_registry=adapters,
    )
    result = orchestrator.run()

    if parsed.video and result.get("success"):
        from core.video_orchestrator import VideoOrchestrator
        vor = VideoOrchestrator(
            run_dir=result["output_dir"],
            fps=parsed.fps,
            duration=parsed.duration,
            scene_count=parsed.scene_count,
        )
        video_result = vor.run()
        result["video"] = video_result
        result["success"] = video_result.get("success", False)

    print(json.dumps(result, indent=2, default=str))

    if result.get("success"):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
