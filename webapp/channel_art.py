"""Banner and watermark drafts for the setup window, made with Gemini.

Two ways, picked automatically:
- artwork: a Gemini image model paints it. Needs a key whose plan includes image models
  (the free tier's limit is 0, so billing must be on).
- design: Gemini Flash-Lite picks the colours, tagline, icon and pattern, and the hub draws
  it in Chromium. Text stays sharp in any script and the sizes are exactly YouTube's.
Either way the result is a draft file in the hub; nothing reaches YouTube until it is saved.
"""

import datetime as dt
import html
import io
import math
import os
import random
import re
from typing import Any, Dict, List, Optional

from content_templates.specs import NICHES
from providers.ai.gemini import Gemini, GeminiError, GeminiQuotaError, pick_image_model
from webapp import ai_drafts, db
from webapp.queue import ActionError

KINDS = ("banner", "watermark")
SIZES = {"banner": (2560, 1440), "watermark": (512, 512)}
EXTENSIONS = {"banner": "jpg", "watermark": "png"}
PATTERNS = ("dots", "bubbles", "stars", "waves", "grid", "rays", "confetti")
STYLES = {  # Google Fonts with Devanagari, so Hindi and Hinglish taglines render properly
    "playful": ("Baloo 2", "800"),
    "bold": ("Poppins", "800"),
    "elegant": ("Playfair Display", "700"),
    "techy": ("Rajdhani", "700"),
}
FALLBACK_FONTS = "'Nirmala UI', 'Noto Sans Devanagari', 'Segoe UI', sans-serif"
NO_QUOTA_SETTING = "gemini_image_no_quota"  # the day the key last had no image quota
HEX = re.compile(r"#?([0-9a-fA-F]{6})")


# ---------- drafts on disk ----------

def draft_path(channel_id: int, kind: str) -> str:
    return os.path.join(db.HUB_DIR, "setup_drafts", f"{channel_id}-{kind}.{EXTENSIONS[kind]}")


def draft_url(channel_id: int, kind: str) -> str:
    return f"/channels/{channel_id}/setup/draft/{kind}?v={int(os.path.getmtime(draft_path(channel_id, kind)))}"


def drafts(channel_id: int) -> Dict[str, str]:
    """The Gemini drafts waiting for this channel, as {kind: url}."""
    return {kind: draft_url(channel_id, kind) for kind in KINDS if os.path.exists(draft_path(channel_id, kind))}


def read_draft(channel_id: int, kind: str) -> bytes:
    path = draft_path(channel_id, kind)
    if not os.path.exists(path):
        raise ActionError(f"There's no Gemini {kind} yet. Press Generate first.")
    with open(path, "rb") as f:
        return f.read()


def discard(channel_id: int, kind: str) -> None:
    try:
        os.remove(draft_path(channel_id, kind))
    except OSError:
        pass


# ---------- generate ----------

def generate(conn, channel_id: int, kinds: List[str], idea: str = "", client=None, services=None) -> Dict[str, Any]:
    """Draw the asked-for drafts. One design is shared, so banner and watermark match."""
    kinds = [k for k in KINDS if k in kinds]
    if not kinds:
        raise ActionError("Pick the banner or the watermark.")
    ctx = _context(conn, channel_id, services)
    idea = re.sub(r"[<>]", "", idea or "").strip()[:300]
    client = client or _client(conn)
    images: Dict[str, bytes] = {}
    note, how = "", "artwork"
    model = _image_model(conn)
    try:
        for kind in kinds if model else []:
            images[kind] = _fit(kind, client.generate_image(_art_prompt(kind, ctx, idea), "16:9" if kind == "banner" else "1:1", model=model))
    except GeminiQuotaError:
        db.set_setting(conn, NO_QUOTA_SETTING, dt.date.today().isoformat())
        images = {}
    except GeminiError as e:
        raise ActionError(str(e))
    if not images:
        how = "design"
        if model or db.get_setting(conn, NO_QUOTA_SETTING):
            note = ("Your Gemini key's plan has no image quota, so Gemini designed it and the hub drew it. "
                    "Turn on billing in Google AI Studio to get painted artwork instead.")
        design = _design(client, ctx, idea)
        images = render(ctx, design, kinds)
    out = {}
    for kind, data in images.items():
        path = draft_path(channel_id, kind)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        out[kind] = draft_url(channel_id, kind)
    return {"drafts": out, "how": how, "note": note}


def _client(conn) -> Gemini:
    key, model = ai_drafts.api_key(), db.get_setting(conn, "gemini_model")
    if not key or not model:
        raise ActionError("Add your Gemini API key in Settings first.")
    return Gemini(key, model)


def _image_model(conn) -> Optional[str]:
    """The image model to try, unless the key was found to have no image quota today."""
    if db.get_setting(conn, NO_QUOTA_SETTING) == dt.date.today().isoformat():
        return None
    return pick_image_model(ai_drafts.models(conn))


def _context(conn, channel_id: int, services=None) -> Dict[str, Any]:
    from webapp.channel_setup import _live_about

    row = conn.execute("SELECT name, niche FROM channels WHERE id = ?", (channel_id,)).fetchone()
    spec = NICHES.get(row["niche"])
    titles = [r[0] for r in conn.execute(
        "SELECT title FROM videos WHERE channel_id = ? ORDER BY COALESCE(publish_at, created_at) DESC LIMIT 12", (channel_id,))]
    live = _live_about(conn, channel_id, services)
    icon, name = split_icon(row["name"])
    return {
        "name": name, "icon": icon, "titles": titles, "about": (live.get("description") or "")[:500],
        "niche": f"{spec.name}: {spec.audience_and_tone}" if spec else "",
    }


def split_icon(name: str):
    """'🦁 Leo Ki Pathshala' -> ('🦁', 'Leo Ki Pathshala')."""
    m = re.match(r"^([^\w\s]+)\s*(.+)$", name.strip())
    return (m.group(1), m.group(2)) if m else ("", name.strip())


def _about_lines(ctx) -> List[str]:
    return [
        f"- Current About text: \"{ctx['about']}\"" if ctx["about"] else "",
        "- Video titles: " + "; ".join(ctx["titles"]) if ctx["titles"] else "",
        f"- Hint only (ignore where it disagrees): the hub files it under {ctx['niche']}" if ctx["niche"] else "",
    ]


# ---------- artwork: an image model paints it ----------

def _art_prompt(kind: str, ctx, idea: str) -> str:
    common = [f"The YouTube channel is \"{ctx['name']}\". What it is:", *_about_lines(ctx)]
    if idea:
        common.append(f"The owner's idea: {idea}")
    if kind == "banner":
        lines = [
            "Design the channel's banner (channel art), a wide 16:9 image.",
            *common,
            f"Write the channel name \"{ctx['name']}\" once, large and spelled exactly, with the main illustration, "
            "all inside the central strip: the middle 60% of the width and the middle 30% of the height. "
            "Everything outside that strip is decorative background with no text, because phones crop it.",
            "Bold, clean and colourful, suited to the audience. No other words, no logos of other brands, no URLs, "
            "no fake buttons, no borders.",
        ]
    else:
        lines = [
            "Design a square YouTube video watermark: a simple round badge icon for the channel that still reads at 60×60 pixels.",
            *common,
            "Flat design, thick shapes, 2-3 colours, high contrast, centred, filling most of the frame, "
            "on a plain pure white background. No small details and no words.",
        ]
    return "\n".join(filter(None, lines))


def _fit(kind: str, raw: bytes) -> bytes:
    """Crop and size an image model's output to what YouTube wants."""
    from PIL import Image, ImageDraw, ImageOps

    image = Image.open(io.BytesIO(raw))
    image = ImageOps.fit(image.convert("RGBA"), SIZES[kind], Image.LANCZOS)
    out = io.BytesIO()
    if kind == "banner":
        image.convert("RGB").save(out, "JPEG", quality=90)
        return out.getvalue()
    # Clear the white background around the badge so only the badge shows on videos.
    w, h = image.size
    for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if image.getpixel(corner)[3] and min(image.getpixel(corner)[:3]) > 215:
            ImageDraw.floodfill(image, corner, (255, 255, 255, 0), thresh=40)
    image.save(out, "PNG", optimize=True)
    return out.getvalue()


# ---------- design: Gemini picks the look, the hub draws it ----------

def _design_schema() -> Dict[str, Any]:
    color = {"type": "STRING", "description": "#RRGGBB"}
    props = {
        "tagline": {"type": "STRING", "description": "Up to 45 characters, in the channel's own language and script style (Hinglish stays Hinglish)."},
        "icon": {"type": "STRING", "description": "One emoji that stands for the channel."},
        "background": color,
        "background_2": {**color, "description": "#RRGGBB, a second background colour for the gradient"},
        "accent": color,
        "pattern": {"type": "STRING", "enum": list(PATTERNS)},
        "style": {"type": "STRING", "enum": list(STYLES)},
        "subscribe_label": {"type": "STRING", "description": "The word SUBSCRIBE, or a short translation, up to 12 characters."},
    }
    order = list(props)
    return {"type": "OBJECT", "properties": props, "required": order, "propertyOrdering": order}


def _design(client, ctx, idea: str) -> Dict[str, Any]:
    prompt = "\n".join(filter(None, [
        f"Design the look of the YouTube channel \"{ctx['name']}\": the banner and a round watermark badge share it.",
        "What the channel is (match its audience and language):", *_about_lines(ctx),
        f"The owner's idea: {idea}" if idea else "",
        "Pick colours that suit the audience; background and background_2 should be close enough to make a smooth gradient, "
        "and accent should stand out on them. Kids' channels: bright and friendly. Serious topics: deep and calm.",
        "No < or > characters.",
    ]))
    try:
        answer = client.generate_json(prompt, _design_schema(), temperature=1.0)
    except GeminiError as e:
        raise ActionError(str(e))
    return clean_design(answer, ctx)


def clean_design(answer: Dict[str, Any], ctx) -> Dict[str, Any]:
    def color(value, fallback):
        m = HEX.fullmatch(value.strip()) if isinstance(value, str) else None  # Gemini often drops the '#'
        return "#" + m.group(1).lower() if m else fallback

    def text(value, limit):
        return re.sub(r"[<>]", "", str(value or "")).strip()[:limit]

    background = color(answer.get("background"), "#1e3a8a")
    return {
        "tagline": text(answer.get("tagline"), 60),
        "icon": ctx["icon"] or text(answer.get("icon"), 8) or "▶",
        "background": background,
        "background_2": color(answer.get("background_2"), background),
        "accent": color(answer.get("accent"), "#facc15"),
        "pattern": answer.get("pattern") if answer.get("pattern") in PATTERNS else "dots",
        "style": answer.get("style") if answer.get("style") in STYLES else "bold",
        "subscribe_label": text(answer.get("subscribe_label"), 12) or "SUBSCRIBE",
    }


def _luminance(hex_color: str) -> float:
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def ink_for(*backgrounds: str) -> str:
    """White or near-black text, whichever has more contrast on these backgrounds."""
    lum = sum(_luminance(c) for c in backgrounds) / len(backgrounds)
    on_white, on_dark = 1.05 / (lum + 0.05), (lum + 0.05) / (_luminance("#111827") + 0.05)
    return "#ffffff" if on_white >= on_dark else "#111827"


def pattern_svg(pattern: str, width: int, height: int, color: str, seed: int) -> str:
    rnd = random.Random(seed)
    shapes: List[str] = []
    if pattern == "dots":
        for x in range(40, width, 80):
            for y in range(40, height, 80):
                shapes.append(f'<circle cx="{x}" cy="{y}" r="6"/>')
    elif pattern == "bubbles":
        for _ in range(55):
            shapes.append(f'<circle cx="{rnd.randint(0, width)}" cy="{rnd.randint(0, height)}" r="{rnd.randint(20, 150)}" opacity="{rnd.uniform(.25, .7):.2f}"/>')
    elif pattern == "stars":
        for _ in range(70):
            x, y, r = rnd.randint(0, width), rnd.randint(0, height), rnd.randint(10, 40)
            shapes.append(f'<path d="M{x} {y - r} L{x + r * .3:.0f} {y - r * .3:.0f} L{x + r} {y} L{x + r * .3:.0f} {y + r * .3:.0f} '
                          f'L{x} {y + r} L{x - r * .3:.0f} {y + r * .3:.0f} L{x - r} {y} L{x - r * .3:.0f} {y - r * .3:.0f} Z"/>')
    elif pattern == "waves":
        for i in range(9):
            y0, amp = 120 + i * 150, rnd.randint(30, 70)
            d = f"M0 {y0} " + " ".join(f"Q{x + 160} {y0 - amp if (x // 320) % 2 == 0 else y0 + amp} {x + 320} {y0}" for x in range(0, width, 320))
            shapes.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="10" stroke-linecap="round"/>')
    elif pattern == "grid":
        shapes += [f'<rect x="{x}" y="0" width="3" height="{height}"/>' for x in range(0, width, 120)]
        shapes += [f'<rect x="0" y="{y}" width="{width}" height="3"/>' for y in range(0, height, 120)]
    elif pattern == "rays":
        cx, cy = width / 2, height / 2
        for i in range(0, 36, 2):
            a, b = i * 10, (i + 1) * 10
            p1 = (cx + 3000 * math.cos(math.radians(a)), cy + 3000 * math.sin(math.radians(a)))
            p2 = (cx + 3000 * math.cos(math.radians(b)), cy + 3000 * math.sin(math.radians(b)))
            shapes.append(f'<path d="M{cx} {cy} L{p1[0]:.0f} {p1[1]:.0f} L{p2[0]:.0f} {p2[1]:.0f} Z" opacity=".5"/>')
    else:  # confetti
        for _ in range(140):
            shapes.append(f'<rect x="{rnd.randint(0, width)}" y="{rnd.randint(0, height)}" width="{rnd.randint(14, 34)}" height="{rnd.randint(6, 12)}" '
                          f'rx="3" transform="rotate({rnd.randint(0, 180)} {rnd.randint(0, width)} {rnd.randint(0, height)})"/>')
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" fill="{color}" opacity=".16">{"".join(shapes)}</svg>'


def banner_html(ctx, design: Dict[str, Any]) -> str:
    w, h = SIZES["banner"]
    family, weight = STYLES[design["style"]]
    ink = ink_for(design["background"], design["background_2"])
    e = html.escape
    return f"""<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family={family.replace(' ', '+')}:wght@500;{weight}&display=block">
<style>
*{{margin:0;box-sizing:border-box}}
body{{width:{w}px;height:{h}px;overflow:hidden;background:linear-gradient(120deg,{design['background']},{design['background_2']});
  font-family:'{family}',{FALLBACK_FONTS};color:{ink};position:relative}}
.pattern{{position:absolute;inset:0}}
.glow{{position:absolute;left:50%;top:50%;width:1900px;height:760px;transform:translate(-50%,-50%);
  background:radial-gradient(closest-side,{design['background']}ee,{design['background']}00)}}
.side{{position:absolute;top:50%;width:520px;height:520px;border-radius:50%;transform:translateY(-50%);background:{design['accent']};opacity:.22}}
.safe{{position:absolute;left:50%;top:50%;width:1546px;height:423px;transform:translate(-50%,-50%);
  display:flex;align-items:center;justify-content:center;gap:56px}}
.icon{{flex:none;width:300px;height:300px;border-radius:50%;background:{design['accent']};display:grid;place-items:center;
  font-size:180px;line-height:1;font-family:'Segoe UI Emoji','Noto Color Emoji',sans-serif;box-shadow:0 18px 50px #0004}}
.text{{min-width:0;max-width:1150px}}
h1{{font-weight:{weight};font-size:150px;line-height:1.02;white-space:nowrap;letter-spacing:-1px;text-shadow:0 6px 24px #0003}}
p{{margin-top:22px;font-weight:500;font-size:62px;line-height:1.15;opacity:.92;white-space:nowrap}}
.rule{{margin-top:22px;width:180px;height:12px;border-radius:6px;background:{design['accent']}}}
</style></head><body>
<div class="pattern">{pattern_svg(design['pattern'], w, h, ink, len(ctx['name']))}</div>
<div class="side" style="left:-200px"></div><div class="side" style="right:-200px"></div>
<div class="glow"></div>
<div class="safe"><div class="icon">{e(design['icon'])}</div>
<div class="text"><h1>{e(ctx['name'])}</h1>{'<div class="rule"></div><p>' + e(design['tagline']) + '</p>' if design['tagline'] else ''}</div></div>
<script>
// Shrink the name and tagline until they fit the safe area.
for (const el of document.querySelectorAll('h1, p')) {{
  let size = parseFloat(getComputedStyle(el).fontSize);
  while (el.scrollWidth > 1150 && size > 40) {{ size -= 4; el.style.fontSize = size + 'px'; }}
}}
</script></body></html>"""


def watermark_html(ctx, design: Dict[str, Any]) -> str:
    w, h = SIZES["watermark"]
    family, weight = STYLES[design["style"]]
    label_ink = ink_for(design["accent"])
    e = html.escape
    return f"""<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family={family.replace(' ', '+')}:wght@{weight}&display=block">
<style>
*{{margin:0;box-sizing:border-box}}
html,body{{width:{w}px;height:{h}px;background:transparent;overflow:hidden}}
.badge{{position:absolute;inset:12px;border-radius:50%;border:22px solid #fff;
  background:linear-gradient(135deg,{design['background']},{design['background_2']});display:grid;place-items:center;overflow:hidden}}
.icon{{font-size:230px;line-height:1;margin-top:-70px;font-family:'Segoe UI Emoji','Noto Color Emoji',sans-serif}}
.label{{position:absolute;left:0;right:0;bottom:0;height:150px;background:{design['accent']};color:{label_ink};
  font-family:'{family}',{FALLBACK_FONTS};font-weight:{weight};font-size:60px;display:grid;place-items:center;padding-bottom:30px;letter-spacing:1px}}
</style></head><body>
<div class="badge"><div class="icon">{e(design['icon'])}</div><div class="label">{e(design['subscribe_label'])}</div></div>
<script>
const label = document.querySelector('.label'); let size = 60;
while (label.scrollWidth > label.clientWidth && size > 28) {{ size -= 2; label.style.fontSize = size + 'px'; }}
</script></body></html>"""


def render(ctx, design: Dict[str, Any], kinds: List[str]) -> Dict[str, bytes]:
    """Draw the designed banner and/or watermark in Chromium at YouTube's sizes."""
    from playwright.sync_api import Error as PlaywrightError, sync_playwright

    pages = {"banner": banner_html, "watermark": watermark_html}
    out: Dict[str, bytes] = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                for kind in kinds:
                    w, h = SIZES[kind]
                    page = browser.new_page(viewport={"width": w, "height": h})
                    try:
                        page.set_content(pages[kind](ctx, design), wait_until="networkidle", timeout=20000)
                    except PlaywrightError:
                        pass  # fonts didn't load (offline): the system fallback fonts are used
                    page.evaluate("document.fonts.ready.then(() => true)")
                    if kind == "banner":
                        out[kind] = page.screenshot(type="jpeg", quality=92)
                    else:
                        out[kind] = page.screenshot(type="png", omit_background=True)
                    page.close()
            finally:
                browser.close()
    except PlaywrightError as e:
        raise ActionError(f"Couldn't draw the image: {e}")
    return out
