import type { SonyOBSApi } from "../preload";

declare global {
  interface Window {
    sonyobs: SonyOBSApi;
  }
}

const $ = <T extends HTMLElement>(sel: string): T => {
  const el = document.querySelector(sel) as T | null;
  if (!el) throw new Error(`missing element: ${sel}`);
  return el;
};

function setPill(state: "ok" | "warn" | "unknown" | "red", text: string): void {
  const pill = $("#pill");
  pill.className = `pill ${state}`;
  pill.textContent = text;
}

function setText(id: string, text: string): void {
  $("#" + id).textContent = text;
}

function setJson(id: string, value: unknown): void {
  setText(id, JSON.stringify(value, null, 2));
}

async function refreshStatus(): Promise<void> {
  try {
    const st = (await window.sonyobs.status()) as { status?: { active: boolean; timecode?: string }; current_scene?: string };
    setPill(st.status?.active ? "ok" : "warn", st.status?.active ? "RECORDING" : "idle");
    setJson("rec-status", st.status ?? {});
    setJson("rec-scene", st.current_scene ?? "—");
  } catch (err) {
    setPill("red", "sidecar down");
  }
}

async function refreshProfiles(): Promise<void> {
  try {
    const { profiles } = (await window.sonyobs.profiles()) as { profiles: Array<{ name: string }> };
    const sel = $("#profile") as HTMLSelectElement;
    sel.innerHTML = "";
    for (const p of profiles) {
      const opt = document.createElement("option");
      opt.value = p.name;
      opt.textContent = p.name;
      sel.appendChild(opt);
    }
  } catch (err) { /* sidecar down — leave as-is */ }
}

async function refreshScenes(): Promise<void> {
  try {
    const data = await window.sonyobs.scenes();
    setJson("scenes", data);
  } catch (err) { /* down */ }
}

async function refreshServices(): Promise<void> {
  try {
    const map = (await window.sonyobs.servicesStatus()) as Record<string, { running: boolean; port: number; detail: string }>;
    const od = map.opendesign;
    const oh = map.openhands;
    if (od) $("#od-status").textContent = `${od.running ? "up" : "stopped"} — :${od.port} ${od.detail}`;
    if (oh) $("#oh-status").textContent = `${oh.running ? "up" : "stopped"} — :${oh.port} ${oh.detail}`;
  } catch (err) {
    $("#od-status").textContent = "docker unavailable";
    $("#oh-status").textContent = "docker unavailable";
  }
}

function setEditCell(id: string, text: string, state: "ok" | "unknown" | "red"): void {
  const cell = $(id);
  cell.textContent = text;
  cell.className = `pill ${state}`;
}

async function refreshEditStatus(): Promise<void> {
  try {
    const { openRouter } = await window.sonyobs.getKeysPresent();
    setEditCell("#er-key", openRouter ? "key saved" : "no key yet", openRouter ? "ok" : "unknown");
  } catch { /* sidecar down — keep as-is */ }
  try {
    const map = (await window.sonyobs.servicesStatus()) as Record<string, { running: boolean; port: number }>;
    const od = map.opendesign;
    const oh = map.openhands;
    if (od) setEditCell("#od-row", od.running ? `up :${od.port}` : "stopped", od.running ? "ok" : "unknown");
    if (oh) setEditCell("#oh-row", oh.running ? `up :${oh.port}` : "stopped", oh.running ? "ok" : "unknown");
  } catch {
    setEditCell("#od-row", "stopped", "red");
    setEditCell("#oh-row", "stopped", "red");
  }
  try {
    const cs = await window.sonyobs.cutroomStatus();
    if (cs) setEditCell("#cr-row", cs.available ? `up${cs.keyPresent ? " · key ok" : ""}` : "no server", cs.available ? "ok" : "unknown");
  } catch { setEditCell("#cr-row", "no server", "unknown"); }
}

async function refreshKeys(): Promise<void> {
  try {
    const { openRouter, deepgram } = await window.sonyobs.getKeysPresent();
    const or = $("#or-present");
    const dg = $("#dg-present");
    or.className = `pill ${openRouter ? "ok" : "unknown"}`;
    or.textContent = openRouter ? "saved" : "absent";
    dg.className = `pill ${deepgram ? "ok" : "unknown"}`;
    dg.textContent = deepgram ? "saved" : "absent";
  } catch (err) { /* ignore */ }
}

function wireTabs(): void {
  const tabs = document.querySelectorAll("nav button");
  tabs.forEach((btn) => {
    const b = btn as HTMLElement;
    b.addEventListener("click", () => {
      tabs.forEach((other) => {
        (other as HTMLElement).classList.remove("active");
      });
      b.classList.add("active");
      const tab = b.dataset.tab ?? "";
      document.querySelectorAll("section.tab").forEach((s) => {
        (s as HTMLElement).classList.toggle("hidden", s.id !== `tab-${tab}`);
      });
    });
  });
}

function wireButtons(): void {
  $("#btn-start").addEventListener("click", async () => {
    const profile = ($("#profile") as HTMLSelectElement).value;
    if (!profile) return;
    try {
      const res = await window.sonyobs.start(profile);
      setJson("rec-meta", res);
      refreshStatus();
    } catch (err: unknown) {
      setJson("rec-meta", err instanceof Error ? err.message : String(err));
    }
  });
  $("#btn-stop").addEventListener("click", async () => {
    try {
      const res = await window.sonyobs.stop();
      setJson("rec-meta", res);
      refreshStatus();
    } catch (err) {
      setJson("rec-meta", err instanceof Error ? err.message : String(err));
    }
  });
  $("#btn-pause").addEventListener("click", async () => {
    try {
      await window.sonyobs.pause();
      refreshStatus();
    } catch (e) {
      setJson("rec-meta", String(e));
    }
  });
  $("#btn-resume").addEventListener("click", async () => {
    try {
      await window.sonyobs.resume();
      refreshStatus();
    } catch (e) {
      setJson("rec-meta", String(e));
    }
  });
  $("#btn-refresh").addEventListener("click", () => { refreshStatus(); refreshProfiles(); refreshScenes(); });
  $("#btn-scan").addEventListener("click", async () => {
    try { setJson("rec-meta", await window.sonyobs.sonyScan()); } catch (e) { setJson("rec-meta", String(e)); }
  });
  $("#save-or").addEventListener("click", async () => {
    await window.sonyobs.saveKey("openRouterKey", ($("#key-or") as HTMLInputElement).value);
    refreshKeys();
    setPill("ok", "key saved");
  });
  $("#save-dg").addEventListener("click", async () => {
    await window.sonyobs.saveKey("deepgramKey", ($("#key-dg") as HTMLInputElement).value);
    refreshKeys();
  });
  $("#clear-keys").addEventListener("click", async () => {
    await window.sonyobs.clearKeys();
    ($("#key-or") as HTMLInputElement).value = "";
    ($("#key-dg") as HTMLInputElement).value = "";
    refreshKeys();
  });
  $("#od-start").addEventListener("click", () => window.sonyobs.serviceStart("opendesign").then(refreshServices));
  $("#od-stop").addEventListener("click", () => window.sonyobs.serviceStop("opendesign").then(refreshServices));
  $("#oh-start").addEventListener("click", () => window.sonyobs.serviceStart("openhands").then(refreshServices));
  $("#oh-stop").addEventListener("click", () => window.sonyobs.serviceStop("openhands").then(refreshServices));
  $("#od-open").addEventListener("click", () => openExternal("http://127.0.0.1:7456"));
  $("#oh-open").addEventListener("click", () => openExternal("http://127.0.0.1:3000"));
  $("#btn-fabric-run").addEventListener("click", async () => {
    const pattern = ($("#fabric-pattern") as HTMLInputElement).value.trim();
    const promptEl = ($("#fabric-prompt") as HTMLTextAreaElement).value;
    const prompt = promptEl.trim();
    if (!pattern) return;
    const out = $("#fabric-out");
    out.textContent = "running…";
    try {
      const res = await window.sonyobs.runFabric(pattern, prompt);
      out.textContent = res.ok ? (res.output ?? "(no output)") : `error: ${res.error ?? "unknown"}`;
    } catch (e) {
      out.textContent = `error: ${e instanceof Error ? e.message : String(e)}`;
    }
  });
$("#btn-cutroom-run").addEventListener("click", async () => {
    const prompt = ($("#cutroom-prompt") as HTMLTextAreaElement).value;
    if (!prompt) return;
    const out = $("#cutroom-out");
    out.textContent = "running…";
    try {
      const res = await window.sonyobs.runCutroom(prompt);
      out.textContent = res.ok ? (res.output ?? "(no output)") : `error: ${res.error ?? "unknown"}`;
    } catch (e) {
      out.textContent = `error: ${e instanceof Error ? e.message : String(e)}`;
    }
  });
}

function openExternal(url: string): void {
  void window.open(url, "_blank");
}

async function boot(): Promise<void> {
  wireTabs();
  wireButtons();
  window.sonyobs.onSidecarState((state) => {
    const map: Record<string, string> = {
      healthy: "ok",
      restarting: "warn",
      unhealthy: "red",
    };
    setPill((map[state] as "ok" | "warn" | "red") ?? "unknown", `sidecar ${state}`);
  });
  await Promise.all([refreshStatus(), refreshProfiles(), refreshScenes(), refreshServices(), refreshKeys(), refreshEditStatus()]);
  setInterval(() => { refreshStatus(); refreshScenes(); }, 3000);
}

void boot();
