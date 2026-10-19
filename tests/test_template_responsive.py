"""Responsive preview checks for the HTML templates.

Every template keeps its original CSS and carries its responsive rules in a
separate <style id="responsive"> block. Two things are checked:

1. Video composition is untouched: at the CSS viewports the renderers use,
   every element has the same box and computed style with the responsive
   block enabled or disabled.
2. Browser previews hold up: at common phone, tablet and desktop sizes no
   text is clipped by its slide, no two text blocks overlap, and the page
   never scrolls sideways.
"""
import glob
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = sorted(glob.glob(os.path.join(ROOT, "templates", "*.html")))
POPULATED = sorted(glob.glob(os.path.join(ROOT, "output", "populated", "*.html")))

# CSS viewports used to render video: TimelineRenderer lays 9:16 out at 360x640 (x3),
# BrowserRenderer uses 1080x1920 and 1920x1080 at x1.
VIDEO_VIEWPORTS = {"9x16": [(360, 640), (1080, 1920)], "16x9": [(1920, 1080)]}

PREVIEW_VIEWPORTS = [
    (320, 568), (390, 844), (844, 390),
    (768, 1024), (1024, 768),
    (1280, 720), (1440, 900), (1920, 1080),
]

# Oversized background numerals that are meant to sit behind the text.
DECORATIVE_CLASSES = ["watermark", "scene", "number", "case-number"]

# Puts every slide in its worst case for layout: typewriter text complete,
# quiz explanations shown.
FILL_TEXT = r"""() => {
  document.querySelectorAll('.slide').forEach(s => {
    clearInterval(s._tw); clearInterval(s._timer);
    s.querySelectorAll('.type[data-text]').forEach(t => { t.textContent = t.dataset.text; });
    const i = Number(s.dataset.index);
    if (window.aiData && !Number.isNaN(i)) { const t = s.querySelector('.typed'); if (t) t.textContent = aiData[i].narration; }
    const ex = s.querySelector('.explain');
    if (ex && s.dataset.i !== undefined && window.quizData) ex.textContent = quizData[+s.dataset.i].explanation;
  });
}"""

LAYOUT_DIFF = r"""() => {
  const props = ['display', 'position', 'width', 'height', 'top', 'left', 'right', 'bottom', 'transform',
    'font-size', 'line-height', 'letter-spacing', 'text-align', 'padding', 'margin', 'border-radius',
    'grid-template-columns', 'justify-content', 'opacity', 'visibility'];
  const snap = () => [...document.querySelectorAll('body *')].map(el => {
    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    return [el.tagName, el.className, r.x, r.y, r.width, r.height, ...props.map(p => cs.getPropertyValue(p))].join('|');
  });
  const sheet = document.getElementById('responsive');
  const on = snap(); sheet.disabled = true; const off = snap(); sheet.disabled = false;
  return on.flatMap((v, i) => v === off[i] ? [] : [`with: ${v}\nwithout: ${off[i]}`]).slice(0, 3);
}"""

MEASURE_SLIDE = r"""([index, decorativeClasses]) => {
  const slides = [...document.querySelectorAll('.slide')];
  const s = slides[index] || document.querySelector('main');
  if (s.parentElement) { s.parentElement.style.scrollBehavior = 'auto'; s.parentElement.scrollTop = s.offsetTop; }
  const box = s.getBoundingClientRect();
  const alpha = c => { const m = c.match(/rgba?\(([^)]+)\)/); const p = m ? m[1].split(',') : []; return p.length > 3 ? parseFloat(p[3]) : 1; };
  const decorative = el => alpha(getComputedStyle(el).color) < 0.12 || decorativeClasses.some(c => el.closest('.' + c));
  const hidden = el => { for (let e = el; e && e !== s; e = e.parentElement) { const c = getComputedStyle(e); if (c.display === 'none' || c.visibility === 'hidden' || parseFloat(c.opacity) === 0) return true; } return false; };
  const blocks = new Map();
  const walker = document.createTreeWalker(s, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode, el = node.parentElement;
    if (!node.textContent.trim() || hidden(el) || decorative(el)) continue;
    let owner = el; while (owner !== s && getComputedStyle(owner).display.startsWith('inline')) owner = owner.parentElement;
    const range = document.createRange(); range.selectNodeContents(node);
    const rects = [...range.getClientRects()].filter(r => r.width > 0 && r.height > 0);
    if (!blocks.has(owner)) blocks.set(owner, []);
    blocks.get(owner).push(...rects);
  }
  const name = el => el.className || el.tagName;
  const issues = [];
  for (const [el, rects] of blocks) for (const r of rects) {
    if (r.left < box.left - 1.5 || r.right > box.right + 1.5 || r.top < box.top - 1.5 || r.bottom > box.bottom + 1.5) {
      issues.push(`'${name(el)}' clipped by the slide`); break;
    }
  }
  const owners = [...blocks.keys()];
  for (let a = 0; a < owners.length; a++) for (let b = a + 1; b < owners.length; b++) {
    if (owners[a].contains(owners[b]) || owners[b].contains(owners[a])) continue;
    const hit = blocks.get(owners[a]).some(p => blocks.get(owners[b]).some(q =>
      Math.min(p.right, q.right) - Math.max(p.left, q.left) > 2 && Math.min(p.bottom, q.bottom) - Math.max(p.top, q.top) > 2));
    if (hit) issues.push(`'${name(owners[a])}' overlaps '${name(owners[b])}'`);
  }
  if (document.documentElement.scrollWidth > innerWidth + 1) issues.push('page scrolls sideways');
  return issues;
}"""


def aspect_of(path):
    return "9x16" if "9x16" in os.path.basename(path) else "16x9"


def chromium_available():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:
        return False


class TestResponsiveBlockPresent(unittest.TestCase):
    def test_every_template_and_populated_file_has_one_responsive_block(self):
        for path in TEMPLATES + POPULATED:
            with open(path, encoding="utf-8") as f:
                html = f.read()
            with self.subTest(file=os.path.basename(path)):
                self.assertEqual(len(re.findall(r'<style id="responsive">', html)), 1)


@unittest.skipUnless(chromium_available(), "Playwright Chromium not installed")
class TestResponsiveTemplates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls._pw = sync_playwright().start()
        cls.browser = cls._pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls._pw.stop()

    def open(self, path, width, height):
        context = self.browser.new_context(viewport={"width": width, "height": height})
        # Remote images and fonts would make layout depend on the network.
        context.route("**/*", lambda route: route.abort() if route.request.url.startswith("http") else route.continue_())
        page = context.new_page()
        with open(path, encoding="utf-8") as f:
            page.set_content(f.read(), wait_until="load")
        page.evaluate(FILL_TEXT)
        self.addCleanup(context.close)
        return page

    def test_responsive_rules_do_not_change_video_composition(self):
        for path in TEMPLATES + POPULATED:
            for width, height in VIDEO_VIEWPORTS[aspect_of(path)]:
                with self.subTest(file=os.path.basename(path), viewport=f"{width}x{height}"):
                    page = self.open(path, width, height)
                    self.assertEqual(page.evaluate(LAYOUT_DIFF), [])

    def test_previews_have_no_clipped_or_overlapping_text(self):
        for path in TEMPLATES + POPULATED:
            for width, height in PREVIEW_VIEWPORTS:
                with self.subTest(file=os.path.basename(path), viewport=f"{width}x{height}"):
                    page = self.open(path, width, height)
                    slide_count = max(1, page.evaluate("document.querySelectorAll('.slide').length"))
                    issues = []
                    for index in range(slide_count):
                        issues += [f"slide {index}: {m}" for m in page.evaluate(MEASURE_SLIDE, [index, DECORATIVE_CLASSES])]
                    self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
