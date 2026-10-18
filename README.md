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

### AI Optimizer: suggestions before upload

Gemini suggests a better title, description and tags (and, for Shorts, a hook, on-screen
text, loop ending and CTA) for videos that aren't on YouTube yet:

- **Gemini drafts:** each video on a draft's review page has a Suggestions panel, and
  "Suggestions for all" runs them all.
- **Queued videos:** the **Suggestions** button in a channel's queue, for videos that are
  ready, rendered or failed and not uploaded.

How it works:

- **One request per video.** It's a single Gemini `generate_json` call (the model picked in
  Settings, e.g. Flash-Lite), sent only a summary: the current metadata, what the video
  covers, the channel's recent titles and its 3 best videos.
- **The hub checks every answer** (`webapp/optimizer.py`) before showing it:
  - YouTube's limits: title 100 characters, description 5,000 bytes, tags 500 characters.
    These are counted together with the channel's description footer and default tags,
    which the upload adds.
  - The channel's language: a Hindi channel gets Devanagari titles and Roman-script tags
    and hashtags.
  - Made for Kids: no comment, reply, bell or notification CTAs.
  - A failing answer is retried once with the problems listed. If it fails again, the
    suggestion fails with a readable error and the video keeps its metadata.
- **Made for Kids is read from two places:** the channel's upload defaults, and YouTube's
  live channel setting (a 1-unit read). The stricter one is used for the rules, and a
  mismatch is shown as a warning. The hub never changes either setting.
- **Applying needs approval.** You see a before/after preview with live limit counters,
  can edit anything, and tick an approval box. Apply changes the draft row or queued video
  **in the hub only**; it goes to YouTube with the upload. The original is backed up and
  **Undo** restores it, unless the metadata was edited again since.

No new environment variables: Gemini uses the key saved in Settings or `GEMINI_API_KEY`.
The table `video_suggestions` is created automatically on start.

Limits:

- It can't change what's inside a video (hook, visuals, audio). The Shorts advice is for
  the next edit.
- Better metadata can improve reach, but it doesn't guarantee views.
- The channel's language and Made for Kids setting come from **Setup → Upload defaults**.
  A channel with no saved defaults is treated as its niche's language.

## Test

```bash
python -m unittest discover -s tests -p "test_*.py"
```
