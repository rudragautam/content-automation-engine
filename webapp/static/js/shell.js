// The app shell: light/dark toggle, channel drawer, per-channel palettes, confirmation dialog,
// toasts, and tables that turn into stacked cards on phones.

const root = document.documentElement;
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

// ---------- toast ----------
const toastEl = document.createElement("div");
toastEl.className = "toast";
toastEl.setAttribute("role", "status");
toastEl.setAttribute("aria-live", "polite");
document.body.appendChild(toastEl);
let toastTimer;
export function toast(text) {
  toastEl.textContent = text;
  toastEl.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.remove("show"), 3600);
}

// ---------- light / dark (independent of the palette, remembered per browser) ----------
document.getElementById("theme-toggle")?.addEventListener("click", () => {
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : !matchMedia("(prefers-color-scheme: light)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("hub-theme", root.dataset.theme); } catch (e) {}
});

// ---------- channel drawer (narrow screens) ----------
const drawer = document.getElementById("channels");
const scrim = document.getElementById("scrim");
const opener = document.getElementById("open-channels");
function openDrawer() {
  drawer?.classList.add("open"); scrim?.classList.add("show");
  opener?.setAttribute("aria-expanded", "true");
  drawer?.querySelector(".ch.on, .ch")?.focus();
}
function closeDrawer() {
  if (!drawer?.classList.contains("open")) return;
  drawer.classList.remove("open"); scrim?.classList.remove("show");
  opener?.setAttribute("aria-expanded", "false");
  opener?.focus();
}
opener?.addEventListener("click", () => (drawer?.classList.contains("open") ? closeDrawer() : openDrawer()));
document.getElementById("close-channels")?.addEventListener("click", closeDrawer);
scrim?.addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

// ---------- palettes ----------
function setPalette(p) {
  root.dataset.palette = p;
  document.querySelectorAll("[data-palette-picker] button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.p === p)));
}
// Switching channel: ease into its palette, then open it.
document.querySelectorAll("a[data-switch]").forEach((a) => {
  a.addEventListener("click", (e) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0 || reduced || a.dataset.palette === root.dataset.palette) return;
    e.preventDefault();
    setPalette(a.dataset.palette);
    setTimeout(() => { location.href = a.href; }, 220);
  });
});
// Theme swatches: save the palette for the active channel.
document.querySelectorAll("[data-palette-picker]").forEach((picker) => {
  picker.addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-p]");
    if (!b || b.disabled || !picker.dataset.channel) return;
    const before = root.dataset.palette;
    setPalette(b.dataset.p);
    try {
      const res = await fetch(`/api/channels/${picker.dataset.channel}/theme`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ theme: b.dataset.p }),
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || "Couldn't save the theme.");
      document.querySelectorAll(`a[data-switch][href$="/channels/${picker.dataset.channel}"], a[data-switch][href*="ch=${picker.dataset.channel}"]`)
        .forEach((a) => { a.dataset.palette = b.dataset.p; });
      toast(`${b.title} theme saved for this channel`);
    } catch (err) {
      setPalette(before);
      toast(err.message);
    }
  });
});

// ---------- confirmation dialog ----------
// confirmDialog({title, text, html, ok, danger}) resolves true when the user continues.
const dialog = document.getElementById("confirm-dialog");
export function confirmDialog({ title = "Are you sure?", text = "", html = null, ok = "Continue", danger = false } = {}) {
  if (!dialog?.showModal) return Promise.resolve(window.confirm([title, text].filter(Boolean).join("\n\n")));
  dialog.querySelector("#confirm-title").textContent = title;
  const body = dialog.querySelector("#confirm-text");
  body.replaceChildren();
  if (html) body.append(html);
  else if (text) { const p = document.createElement("p"); p.textContent = text; body.append(p); }
  const okBtn = dialog.querySelector("[data-confirm-ok]");
  okBtn.textContent = ok;
  okBtn.className = danger ? "btn danger solid" : "btn primary";
  return new Promise((resolve) => {
    const done = (value) => { dialog.close(); cleanup(); resolve(value); };
    const onOk = () => done(true), onCancel = () => done(false), onClose = () => { cleanup(); resolve(false); };
    function cleanup() {
      okBtn.removeEventListener("click", onOk);
      dialog.querySelector("[data-confirm-cancel]").removeEventListener("click", onCancel);
      dialog.removeEventListener("cancel", onClose);
    }
    okBtn.addEventListener("click", onOk);
    dialog.querySelector("[data-confirm-cancel]").addEventListener("click", onCancel);
    dialog.addEventListener("cancel", onClose, { once: true });
    dialog.showModal();
    okBtn.focus();
  });
}
// Forms marked data-confirm="text" (plus optional data-confirm-title / -ok / -danger) ask first.
document.addEventListener("submit", async (e) => {
  const form = e.target;
  if (!(form instanceof HTMLFormElement) || !form.dataset.confirm || form.dataset.confirmed) return;
  e.preventDefault();
  const yes = await confirmDialog({ title: form.dataset.confirmTitle || "Are you sure?", text: form.dataset.confirm,
    ok: form.dataset.confirmOk || "Continue", danger: "confirmDanger" in form.dataset });
  if (!yes) return;
  form.dataset.confirmed = "1";
  form.requestSubmit(e.submitter || undefined);
});

// ---------- tables: label each cell, so on phones rows become stacked cards ----------
document.querySelectorAll(".table-wrap").forEach((wrap) => {
  const table = wrap.querySelector("table");
  const heads = table ? [...table.querySelectorAll("thead th")].map((th) => th.textContent.trim()) : [];
  if (!heads.length) return;
  wrap.classList.add("stack-sm");
  table.querySelectorAll("tbody tr").forEach((tr) => {
    [...tr.children].forEach((td, i) => { if (heads[i] && !td.dataset.label) td.dataset.label = heads[i]; });
  });
});
