import { mountAll } from "./charts.js";

const toastEl = document.createElement("div");
toastEl.className = "toast";
toastEl.setAttribute("role", "status");
document.body.appendChild(toastEl);
let toastTimer;
export function toast(text) {
  toastEl.textContent = text;
  toastEl.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.remove("show"), 3200);
}

async function post(url, body) {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

// Theme: OS setting by default, toggle stored per browser.
const root = document.documentElement;
try { const t = localStorage.getItem("hub-theme"); if (t) root.dataset.theme = t; } catch (e) {}
document.getElementById("theme-toggle")?.addEventListener("click", () => {
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("hub-theme", root.dataset.theme); } catch (e) {}
});

document.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-action]");
  if (!btn) return;
  const row = btn.closest("[data-video]");
  const id = row?.dataset.video;
  const action = btn.dataset.action;
  try {
    if (action === "edit-time") {
      row.classList.add("editing");
      row.querySelector("input[type=datetime-local]")?.focus();
    } else if (action === "cancel-time") {
      row.classList.remove("editing");
    } else if (action === "save-time") {
      const value = row.querySelector("input[type=datetime-local]").value;
      const res = await post(`/api/videos/${id}/schedule`, { publish_at: value });
      row.querySelector(".when-text").textContent = res.label;
      row.classList.remove("editing");
      toast("Publish time saved");
    } else if (action === "render") {
      btn.disabled = true;
      await post(`/api/videos/${id}/render`);
      setStatus(row, "rendering");
      toast("Rendering started. This takes about a minute.");
      poll(id, row);
    } else if (action === "youtube") {
      btn.disabled = true;
      const res = await post(`/api/videos/${id}/youtube`);
      if (res.status === "uploading") {
        setStatus(row, "uploading");
        toast("Uploading to YouTube…");
        poll(id, row);
      } else {
        toast("Scheduled (mock channel, nothing uploaded)");
        setTimeout(() => location.reload(), 600);
      }
    } else if (action === "sync") {
      btn.disabled = true;
      toast("Syncing from YouTube…");
      const res = await post(`/api/channels/${btn.dataset.channel}/sync`);
      toast(`Synced ${res.days} days of stats and ${res.videos} videos`);
      setTimeout(() => location.reload(), 900);
    } else if (action === "disconnect") {
      if (!confirm("Disconnect this channel? Uploads stop until you connect it again.")) return;
      await post(`/api/channels/${btn.dataset.channel}/disconnect`);
      location.reload();
    } else if (action === "delete-video") {
      if (!confirm("Remove this video from the queue?")) return;
      await post(`/api/videos/${id}/delete`);
      row.remove();
      toast("Removed from the queue");
    } else if (action === "delete-audio") {
      if (!confirm("Delete this track? Videos already rendered keep their audio.")) return;
      await post(`/api/audio/${btn.dataset.id}/delete`);
      btn.closest("tr").remove();
      toast("Track deleted");
    } else if (action === "save-slots") {
      const form = btn.closest("[data-slots]");
      const slots = [...form.querySelectorAll("input[type=time]")].map((i) => i.value).filter(Boolean);
      const res = await post(`/api/channels/${form.dataset.slots}/slots`, { slots });
      toast(`Publish slots saved: ${res.slots.join(", ")}`);
    } else if (action === "add-slot") {
      const list = btn.closest("[data-slots]").querySelector(".slot-list");
      const input = document.createElement("input");
      input.type = "time"; input.value = "12:00";
      list.appendChild(input);
      input.focus();
    }
  } catch (err) {
    btn.disabled = false;
    toast(err.message);
  }
});

const STATUS = {
  rendering: ["accent spin", "", "Rendering"],
  rendered: ["accent", "▶", "Rendered"],
  uploading: ["accent spin", "", "Uploading"],
  scheduled: ["accent", "◷", "Scheduled"],
  failed: ["critical", "✕", "Failed"],
};
function setStatus(row, status) {
  const chip = row.querySelector(".chip");
  if (!chip || !STATUS[status]) return;
  const [cls, icon, label] = STATUS[status];
  chip.className = "chip " + cls;
  chip.replaceChildren();
  const i = document.createElement("span"); i.className = "i"; i.textContent = icon;
  chip.append(i, document.createTextNode(label));
}
async function poll(id, row) {
  const res = await fetch(`/api/videos/${id}`).then((r) => r.json());
  if (res.status === "rendering") return setTimeout(() => poll(id, row), 3000);
  if (res.status === "uploading") {
    const chip = row.querySelector(".chip");
    if (chip) chip.lastChild.textContent = `Uploading ${Math.round(res.upload_progress || 0)}%`;
    return setTimeout(() => poll(id, row), 2000);
  }
  setStatus(row, res.status);
  if (res.status === "scheduled") toast("Uploaded and scheduled on YouTube");
  else if (res.error) toast(res.error);
  else toast(res.status === "rendered" ? "Video rendered" : `Status: ${res.status}`);
  setTimeout(() => location.reload(), 900);
}
document.querySelectorAll("[data-video][data-status=rendering], [data-video][data-status=uploading]").forEach((row) => poll(row.dataset.video, row));

// A draft being written by Gemini: reload once it's done.
const draftBox = document.querySelector("[data-draft-poll]");
if (draftBox) {
  const check = async () => {
    const res = await fetch(`/api/drafts/${draftBox.dataset.draftPoll}`).then((r) => r.json()).catch(() => ({}));
    if (res.status === "generating" || !res.status) return setTimeout(check, 3000);
    location.reload();
  };
  setTimeout(check, 3000);
}

// AI Optimizer: reload once Gemini's suggestions are written.
document.querySelectorAll("[data-suggest-poll]").forEach((box) => {
  const check = async () => {
    const res = await fetch(`/api/suggestions/${box.dataset.suggestPoll}`).then((r) => r.json()).catch(() => ({}));
    if (res.status === "generating" || !res.status) return setTimeout(check, 3000);
    location.reload();
  };
  setTimeout(check, 3000);
});

// A channel analysis in progress: reload once the report is saved.
const auditBox = document.querySelector("[data-analysis-poll]");
if (auditBox) {
  const check = async () => {
    const res = await fetch(`/api/analysis/${auditBox.dataset.analysisPoll}`).then((r) => r.json()).catch(() => ({}));
    if (res.status === "running" || !res.status) return setTimeout(check, 3000);
    location.reload();
  };
  setTimeout(check, 3000);
}

// Suggestions form: pick a title, and keep the "After" preview and YouTube's limits in step with edits.
// Counted the way the upload sends it: the channel's footer and default tags are added (webapp/metadata_apply.py).
const LIMITS = { title: 100, description: 5000, tags: 500 };
const bytes = (s) => new TextEncoder().encode(s).length;
const tagsLength = (tags) => tags.reduce((n, t) => n + t.length + (t.includes(" ") ? 2 : 0), 0) + Math.max(tags.length - 1, 0);
const parseTags = (text) => {
  const seen = new Set();
  return text.replace(/\n/g, ",").split(",").map((t) => t.trim()).filter((t) => t && !seen.has(t.toLowerCase()) && seen.add(t.toLowerCase()));
};
document.querySelectorAll("[data-suggest-form]").forEach((form) => {
  const title = form.elements.title, description = form.elements.description, tags = form.elements.tags;
  const footer = form.dataset.footer || "";
  const defaults = parseTags(form.dataset.defaultTags || "");
  const out = (k) => form.querySelector(`[data-after=${k}]`);
  const count = (k) => form.querySelector(`[data-count=${k}]`);
  const problems = form.querySelector("[data-limit-problems]");
  const update = () => {
    const t = title.value.split(/\s+/).join(" ").trim();
    const desc = [description.value.trim(), footer].filter(Boolean).join("\n\n");
    const own = parseTags(tags.value);
    const lower = new Set(own.map((x) => x.toLowerCase()));
    const allTags = own.concat(defaults.filter((d) => !lower.has(d.toLowerCase())));
    const sizes = { title: t.length, description: bytes(desc), tags: tagsLength(allTags) };
    out("title").textContent = t || "—";
    out("description").textContent = desc || "(no description)";
    out("tags").textContent = allTags.join(", ") || "(no tags)";
    const bad = [];
    for (const k of Object.keys(LIMITS)) {
      const unit = k === "description" ? "bytes" : "characters";
      count(k).textContent = `${sizes[k]}/${LIMITS[k]} ${unit}`;
      const over = sizes[k] > LIMITS[k];
      count(k).classList.toggle("over", over);
      if (over) bad.push(`The ${k} is ${sizes[k]} ${unit}; YouTube allows ${LIMITS[k]}.`);
    }
    if (!t) bad.push("The title is empty.");
    problems.hidden = !bad.length;
    problems.textContent = bad.join(" ");
    // Apply stays off until the change fits YouTube's limits and the approval box is ticked.
    form.querySelector("[data-apply]").disabled = bad.length > 0 || !form.querySelector("[data-approve]").checked;
    form.querySelectorAll("[data-title-option]").forEach((b) => b.classList.toggle("on", b.dataset.titleOption === t));
  };
  form.querySelectorAll("[data-title-option]").forEach((b) => b.addEventListener("click", () => { title.value = b.dataset.titleOption; update(); }));
  [title, description, tags].forEach((el) => el.addEventListener("input", update));
  form.querySelector("[data-approve]").addEventListener("change", update);
  update();
});

// Analysis report: a link to one video (#s-12) opens its row; filter chips show one kind of video.
const openFromHash = () => {
  const row = location.hash.length > 1 && document.querySelector(`details.video-row#${CSS.escape(location.hash.slice(1))}`);
  if (row) { row.open = true; row.scrollIntoView({ block: "start" }); }
};
openFromHash();
window.addEventListener("hashchange", openFromHash);
document.querySelectorAll("[data-video-filter]").forEach((bar) => {
  bar.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-filter]");
    if (!b) return;
    bar.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
    document.querySelectorAll("details.video-row").forEach((row) => {
      row.hidden = b.dataset.filter !== "all" && row.dataset.state !== b.dataset.filter;
    });
  });
});

mountAll();

// Channel setup opens in its own window, reused if it's already open for that channel.
document.addEventListener("click", (e) => {
  const link = e.target.closest("[data-setup-window]");
  if (!link || e.ctrlKey || e.metaKey || e.shiftKey) return;
  e.preventDefault();
  const w = Math.min(1200, screen.availWidth - 40), h = Math.min(920, screen.availHeight - 40);
  const win = window.open(link.href, link.target, `width=${w},height=${h},left=${(screen.availWidth - w) / 2},top=20`);
  if (win) win.focus(); else location.href = link.href;  // popup blocked: open here instead
});

// Channel names from Gemini. A [data-name-suggest] box either fills the add-channel form ("fill"),
// renames a planned channel ("rename") or copies the name for YouTube Studio ("copy").
document.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-name-suggest] [data-suggest]");
  if (!btn) return;
  const box = btn.closest("[data-name-suggest]");
  const status = box.querySelector("[data-status]"), results = box.querySelector("[data-results]");
  const body = new FormData();
  body.append("idea", box.querySelector("[data-idea]").value);
  if (box.dataset.channel) body.append("channel_id", box.dataset.channel);
  if (box.dataset.nicheFrom) body.append("niche", document.querySelector(box.dataset.nicheFrom).value);
  btn.disabled = true;
  status.hidden = false; status.className = "notice gen-status";
  status.textContent = "Gemini is thinking of names…";
  try {
    const res = await fetch("/api/channel-names", { method: "POST", body });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Gemini couldn't suggest names.");
    results.replaceChildren(...data.names.map((n) => nameCard(box, n)));
    status.className = "notice ok gen-status";
    status.textContent = "Pick one, or press Suggest again for more. Check the @handle is free on YouTube when you create the channel.";
  } catch (err) {
    status.className = "notice bad gen-status"; status.textContent = err.message;
  }
  btn.disabled = false;
});

function nameCard(box, n) {
  const card = document.createElement("div");
  card.className = "name-card";
  const title = document.createElement("strong"); title.textContent = n.name;
  const handle = document.createElement("span"); handle.className = "muted"; handle.textContent = n.handle;
  const angle = document.createElement("p"); angle.className = "secondary"; angle.textContent = n.angle;
  const action = document.createElement("button");
  action.type = "button"; action.className = "btn small";
  const mode = box.dataset.mode;
  if (mode === "fill") {
    action.textContent = "Use this name";
    action.addEventListener("click", () => {
      for (const [key, value] of Object.entries({ name: n.name, handle: n.handle, angle: n.angle })) {
        const field = document.querySelector(`${box.dataset.form} [name="${key}"]`);
        if (field) { field.value = value; field.classList.add("ai-filled"); }
      }
      document.querySelector(box.dataset.form).scrollIntoView({ behavior: "smooth", block: "center" });
    });
  } else if (mode === "rename") {
    action.textContent = "Rename to this";
    action.className = "btn small primary";
    action.addEventListener("click", () => {
      const form = document.createElement("form");
      form.method = "post"; form.action = `/channels/${box.dataset.channel}/setup/name`;
      for (const [key, value] of Object.entries({ name: n.name, handle: n.handle, angle: n.angle })) {
        const input = document.createElement("input"); input.type = "hidden"; input.name = key; input.value = value;
        form.appendChild(input);
      }
      document.body.appendChild(form); form.submit();
    });
  } else {
    action.textContent = "Copy name";
    action.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(n.name); toast(`Copied “${n.name}”. Paste it in YouTube Studio.`); }
      catch (err) { toast("Couldn't copy; select the name and copy it."); }
    });
  }
  const head = document.createElement("div"); head.className = "name-card-head"; head.append(title, handle);
  card.append(head, angle, action);
  return card;
}
