# Content Automation Engine

Reusable, platform-agnostic foundation for content automation.

## Architecture

- `core/` — pipeline contracts and orchestration.
- `config/` — niche-specific settings, kept outside the core engine.
- `providers/` — adapters for platforms, accounts, and external services.
- `generators/` — content and creative generation.
- `templates/`, `prompts/`, `media/` — reusable assets and inputs.
- `publishing/` — distribution adapters.
- `workflows/` — composable workflow definitions.

Phase 1 intentionally contains no niche-specific News Engine, paid APIs, or unnecessary runtime dependencies.

## Video workflows

Every niche template (01–08, 14, 15) is data-driven: `workflows/` fills `introData` and the
slide array from content, decides each slide's duration from its text (reading or typing
time, quiz reveal beats) and drives the page through `window.__engine.goTo(index, ms)`
on a paused virtual clock, so frames are exact at 1080×1920 (9:16) or 1920×1080 (16:9).

```bash
python engine.py --template 04_Science_Quiz_9x16 --input content.json        # one video
python -m content_templates build                                            # Excel templates per niche
```

## Content hub

```bash
pip install -r requirements.txt && python -m playwright install chromium
python -m webapp --port 8000
```

One dashboard for every channel: connect YouTube channels with Google sign-in, upload a
niche's Excel sheet or let Gemini write it, review, render, pick random background audio,
schedule and upload. Secrets stay in `output/hub/secrets/` (git-ignored).

## Test

```bash
python -m unittest discover -s tests -p "test_*.py"
```
