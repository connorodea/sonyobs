import { app, BrowserWindow, ipcMain, safeStorage, session } from "electron";
import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { openRouterHandlers, type StoredKeys } from "./openrouter";
import { Sidecar } from "./sidecar";
import { ManagedCompose, type ServiceId } from "./managedCompose";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// In dev, this repo root is the parent of electron/. Packaged apps (M5)
// ship a bundled Python binary under resources/python instead.
const REPO_ROOT = app.isPackaged
  ? path.resolve(process.resourcesPath!, "python")
  : path.resolve(__dirname, "..", "..");

const SIDECAR_CMD = (process.env.SONYOBS_SIDECAR ?? "uv").split(" ")[0]!;
const SIDECAR_ARGS = (process.env.SONYOBS_SIDECAR ?? "uv").split(" ").slice(1);

let win: BrowserWindow | null = null;
let sidecar: Sidecar | null = null;
const compose = new ManagedCompose();

function repoRootFor(service: ServiceId): string {
  return path.join(os.homedir(), ".local", "share", "sonyobs-services", service);
}

async function ensureProject(service: ServiceId, gitUrl: string): Promise<void> {
  const dir = repoRootFor(service);
  if (!existsSync(path.join(dir, ".git"))) {
    await execFile("git", ["clone", "--depth", "1", gitUrl, dir]);
  }
}

function createWindow(): void {
  win = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 940,
    minHeight: 640,
    title: "SonyOBS Studio",
    backgroundColor: "#1a1a1e",
    webPreferences: {
      preload: path.join(__dirname, "..", "preload", "index.js"),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
    },
  });

  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        "Content-Security-Policy": [
          "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' ws: http://127.0.0.1:* ",
        ],
      },
    });
  });

  win.loadFile(path.join(__dirname, "..", "renderer", "index.html"));
}

function baseUrl(): string {
  if (!sidecar) {
    throw new Error("sidecar not running");
  }
  return `http://127.0.0.1:${sidecar.port}`;
}

async function apiGet<T>(route: string): Promise<T> {
  const res = await fetch(`${baseUrl()}${route}`);
  if (!res.ok) {
    throw new Error(`GET ${route} -> ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as T;
}

async function apiPost<T>(route: string, body?: unknown): Promise<T> {
  const res = await fetch(`${baseUrl()}${route}`, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    throw new Error(`POST ${route} -> ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as T;
}

function registerIpc(): void {
  ipcMain.handle("capture:health", () => apiGet("/health"));
  ipcMain.handle("capture:status", () => apiGet("/status"));
  ipcMain.handle("capture:profiles", () => apiGet("/profiles"));
  ipcMain.handle("capture:scenes", () => apiGet("/scenes"));
  ipcMain.handle("capture:sources", () => apiGet("/sources"));
  ipcMain.handle("capture:sonyScan", () => apiGet("/sony/scan"));
  ipcMain.handle("capture:start", (_event, profile: string) => apiPost("/recording/start", { profile }));
  ipcMain.handle("capture:stop", () => apiPost("/recording/stop"));
  ipcMain.handle("capture:pause", () => apiPost("/recording/pause"));
  ipcMain.handle("capture:resume", () => apiPost("/recording/resume"));

  ipcMain.handle("settings:getKeys", (): Promise<StoredKeys> => openRouterHandlers.getStoredKeys());
  ipcMain.handle("settings:setKeys", (_event, keys: StoredKeys): Promise<StoredKeys> => openRouterHandlers.setStoredKeys(keys));
  ipcMain.handle("settings:clearKeys", (): Promise<StoredKeys> => openRouterHandlers.clearKeys());

  ipcMain.handle("services:status", async (): Promise<Record<string, unknown>> => {
    const out: Record<string, unknown> = {};
    for (const id of ["opendesign", "openhands"] as ServiceId[]) {
      out[id] = await compose.status(id);
    }
    return out;
  });

  ipcMain.handle("services:start", async (_event, id: ServiceId, keys: StoredKeys = {}) => {
    try {
      await ensureProject(id, id === "opendesign" ? "https://github.com/nexu-io/open-design.git" : "https://github.com/OpenHands/OpenHands.git");
    } catch (err) {
      return { running: false, port: 0, image: "", detail: `clone failed: ${(err as Error).message}` };
    }
    const env: Record<string, string> = {
      LLM_BASE_URL: "https://openrouter.ai/api/v1",
      LLM_API_KEY: keys.openRouterKey ?? "",
    };
    if (id === "opendesign") {
      env.OPENAI_API_KEY = keys.openRouterKey ?? "";
      env.OPENAI_BASE_URL = "https://openrouter.ai/api/v1";
      env.OPENAI_MODEL = "deepseek/deepseek-v4-flash-0731";
    }
    return compose.up(id, env);
  });

  ipcMain.handle("services:stop", (_event, id: ServiceId) => compose.down(id));

  ipcMain.handle("edit:runFabric", async (_event, pattern: string, prompt: string) => {
    try {
      const status = await compose.up("fabric");
      if (typeof status.detail === "string" && /error/i.test(status.detail)) throw new Error(status.detail);
      const dir = repoRootFor("fabric");
      let bin = path.join(dir, "fabric");
      if (!existsSync(bin)) bin = path.join(dir, "bin", "fabric");
      if (!existsSync(bin)) {
        if (!existsSync(path.join(dir, "go.mod"))) throw new Error("fabric clone present but no go.mod buildable CLI — read its README for the run command");
        bin = path.join(os.tmpdir(), "sonyobs-fabric");
        await execCapture("go", ["build", "-o", bin, "."], { cwd: dir, timeout: 240000 });
      }
      const out = await execCapture(bin, ["-p", pattern, "-s", prompt], { cwd: dir, timeout: 120000 });
const capped = out.length > 4000 ? `${out.slice(0, 4000)}\n\u2026[truncated]` : out;
      return { ok: true, output: capped };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return { ok: false, error: msg };
    }
  });
}

function execCapture(file: string, args: string[], opts: { cwd: string; timeout: number }): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile(file, args, { cwd: opts.cwd, timeout: opts.timeout, maxBuffer: 16 * 1024 * 1024, killSignal: "SIGKILL" }, (err, stdout) => {
      if (err) reject(err);
      else resolve(stdout.trim());
    });
  });
}

app.whenReady().then(() => {
  registerIpc();

  sidecar = new Sidecar({
    cmd: SIDECAR_CMD,
    args: [...SIDECAR_ARGS, "api", "--host", "127.0.0.1"],
    cwd: REPO_ROOT,
    portEnv: "API_PORT",
  });

  sidecar.on("state", (state: string) => {
    win?.webContents.send("sidecar:state", state);
  });

  sidecar.start();
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", async () => {
  sidecar?.stop();
  await compose.downAll();
});

for (const sig of ["SIGINT", "SIGTERM", "SIGQUIT"] as const) {
  process.on(sig, () => app.quit());
}
