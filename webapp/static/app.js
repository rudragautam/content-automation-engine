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

mountAll();
