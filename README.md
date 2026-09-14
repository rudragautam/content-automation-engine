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

## Test

```bash
python -m unittest discover -s tests -p "test_*.py"
```
