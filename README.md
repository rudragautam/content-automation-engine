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

### AI Optimizer: channel analysis and changes on YouTube

On a connected channel's page, **Run analysis** (in the AI Optimizer card) does the
following, in the background (`webapp/channel_audit.py`):

1. **Syncs the channel**, like the Sync button.
2. **Reads data from YouTube (read-only).** From the Analytics API, for the last 28 days
   (per video, the last 90): per-video views, % viewed, likes, shares and subscribers
   gained; traffic sources; and the Shorts/long-form split. Analytics API calls don't use
   the Data API's 10,000 units. From the Data API, each video's live title, description,
   tags and Made for Kids setting, at 1 unit per 50 videos.
3. **Runs the rule-based checks** in `webapp/optimizer_checks.py`. No AI and no cost; every
   finding carries its numbers. The checks cover:
   - low retention (Shorts under 70% viewed, long videos under 35%)
   - little traffic from YouTube's recommendations or from search
   - batch uploads, gaps between uploads, or a long time since the last upload
   - weak titles, descriptions or tags, and no playlists
   - Shorts against long-form
   - the trend against the previous 28 days (ending at the last day YouTube has data for)
   - likes and shares per 1,000 views
   - what the top 3 videos share that the bottom 3 don't
   
   With fewer than 100 views (channel) or 30 views (video), it says **"Not enough data
   yet"** instead of a reason.
4. **Saves the report** in `channel_audits`, with a 0–100 health score from the checks.
5. **Asks Gemini about the weakest videos**, 10 by default or all of them: one request per
   video, sent only that video's numbers and the channel's main findings. Besides titles,
   description, tags and the Shorts hook, the answer has a health score, a summary,
   reasons each tied to a number, 5–7 ranked actions and 3 follow-up ideas. Reasons
   without a number are dropped, and so are all reasons for a video with too little data.
   On Made for Kids videos, advice about comments, notifications, end screens, cards or
   community posts is dropped. Without a Gemini key, the rule-based report is still saved.

**Applying a suggestion** changes the video on YouTube with `videos.update`, using the
**snippet part only**. The category and languages are kept; privacy and Made for Kids are
never sent, so they can't change. It works like this (`webapp/metadata_apply.py`):

- **Approval:** you see the live version next to the new one and must tick the approval box.
- **Fresh read:** the hub re-reads the live video first (1 unit) and refuses if it changed
  since the preview, for example in Studio.
- **7-day warning:** if the video's metadata changed in the last 7 days, a second
  "Change it anyway" tick is needed, because changing too often makes results impossible
  to measure.
- **Backup first:** the old value of each field is written to `metadata_changes` before
  YouTube is called. That table also logs the video, field, old value, new value and time.
- **Cost:** about 51 quota units.
- **Rollback:** "Roll back" (in the panel or in **Changes on YouTube** on the channel page)
  restores the backup, unless the video was edited again since.
- **Errors:** quota, expired sign-in, timeouts and network errors give a readable message,
  and the log shows the change as failed.

**Impressions and CTR (phase 2):** the Analytics API v2 doesn't serve them. A live check on
2026-10-18 returned "The query is not supported". They come only from the **YouTube
Reporting API** (report type `channel_reach_basic_a1`). That needs a reporting job created
once per channel with the same sign-in, and its daily CSV files start about 48 hours later.
`publishing.youtube.reach_metrics` is where that source plugs in; until then the report
says CTR isn't available and points to Studio's Reach tab.

### AI Optimizer: reports and comparison

Every analysis is saved, so you can track progress month to month:

- **History:** "All analyses" on the report page, and "Earlier analyses" on the channel page.
- **Comparison:** "Since the previous analysis" on the report page, or **Compare** for any
  two analyses (`/channels/{id}/analysis/{a}/compare/{b}`). It shows the score, views,
  % viewed, recommendation share, search share and likes per 1,000 views, plus which
  problems were **fixed**, which are **new** and which are **still open**.
- **Did the changes help?** For each change made on YouTube in the last 90 days, the
  video's views in the 7 days before against the 7 days after (one read-only Analytics
  query each). A change is measured once 7 days, plus YouTube's 3-day delay, have passed.

Limits:

- It can't change what's inside a video (hook, visuals, audio). The Shorts advice is for
  the next edit.
- YouTube's analytics lag 2–3 days, and very small channels get few breakdowns.
- One video's views before and after a change are a hint, not proof: season, other
  uploads and outside shares move views too.
- Better metadata can improve reach, but it doesn't guarantee views.
- The channel's language and Made for Kids setting come from **Setup → Upload defaults**.
  A channel with no saved defaults is treated as its niche's language.

## Design system

The hub uses a glass design: frosted cards over a soft gradient with blurred colour blobs.
It works in light and dark, at every width from a 360 px phone up.

**Themes.** There are 7 palettes: Sunset, Aurora, Blossom, Forest, Midnight, Ember and
Graphite.
- **Per channel:** each channel stores its palette in `channels.theme`. Empty means Ember.
- **Whole app:** the app wears the active channel's palette through
  `<html data-palette="…">`.
- **Changing it:** use the swatches in the top bar or in **Set up channel → Theme in the
  hub**. Both save through `POST /api/channels/{id}/theme`.
- **Light or dark:** follows the system, or the moon/sun toggle. The choice is remembered
  in the browser (`localStorage["hub-theme"]`) and works with every palette.

**Tokens** (`webapp/static/css/tokens.css`):
- **Palette values:** the approved values, `--bg1`, `--bg2`, `--blob1-3`, `--glass`,
  `--line`, `--text`, `--muted`, `--coral`, `--teal`, `--amber`, `--red` and
  `--btn1/2`, for each palette in light and dark.
- **Semantic tokens** derived from them:
  - `--primary` (button gradient)
  - `--ink-muted` and `--link`: text colours mixed until they pass WCAG AA on glass
  - `--card-bg` and `--tint`: a stronger backing under long text and tables
  - type sizes from `--fs-xs` (14 px, the smallest anywhere) to `--fs-page` (30 px)
  - spacing `--s1` to `--s8`, radii, `--blur`, `--tap` (48 px targets) and motion timings
- **Without backdrop-filter**, cards fall back to a solid, slightly see-through
  background.

**Styles** (`webapp/static/css/`):
- `base.css`: reset, type, background, focus and reduced motion.
- `layout.css`: the shell (left navigation, top bar, Channels menu and drawer, phone tab
  bar).
- `components.css`: buttons, inputs, toggles, tabs, badges, notices, stat cards, score
  ring, problem cards, tables (stacked cards on phones), dialogs, toasts, empty states,
  skeletons and chart styles.
- `pages.css`: page-specific pieces.

**Templates:**
- `base.html`: the shell.
- `_ui.html`: macros `icon`, `stat`, `ring`, `empty_state` and `issue`.
- `_macros.html`: status chips, deltas, filters and queue rows.
- `_suggest.html` and `_reports.html`: AI Optimizer pieces.

**Scripts:**
- `static/js/shell.js`: theme toggle, Channels drawer, palette swatches, `confirmDialog()`,
  `toast()`, and labelling table cells for the stacked phone layout.
- A form with `data-confirm="…"` (plus optional `data-confirm-title`, `-ok`, `-danger`)
  asks in the glass dialog first.
- `webapp/shell.py` decides the active channel and where each Channels menu entry leads.

**Adding a page:**
1. Make it extend `base.html`.
2. Fill `{% block page_title %}`, `{% block page_desc %}` (one line) and, for its single
   main action, `{% block page_actions %}` with one `btn primary`.
3. Put content in `{% block content %}`, grouped into `<section class="card">` with a
   `card-head` and an `<h2>`.
4. Use the `_ui.html` macros for stats, empty states and scores, and `table-wrap` for
   tables, which stack on phones automatically.
5. Put rarely used options in `<details class="more">`.
6. Add the page to `SECTIONS` in `webapp/shell.py`, so the right navigation item lights up.

The font is Plus Jakarta Sans (SIL Open Font License), bundled in `static/fonts`, so the hub
works offline.

## Test

```bash
python -m unittest discover -s tests -p "test_*.py"
```
