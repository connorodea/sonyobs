import { execFile } from "node:child_process";
import { promises as fs } from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";

export type ServiceId = "opendesign" | "openhands" | "fabric";

export interface ServiceStatus {
  running: boolean;
  port: number;
  image: string;
  detail: string;
}

interface ServiceInfo {
  image: string;
  port: number;
  composeYaml: string;
}

const OPEN_DESIGN_YAML = `\
services:
  open-design:
    image: ghcr.io/nexu-io/od:latest
    ports:
      - "127.0.0.1:7456:7456"
    environment:
      OD_API_TOKEN: "local-dev"
      OPEN_DESIGN_ALLOWED_ORIGINS: "http://localhost"
      OPENAI_API_KEY: "\${OPENAI_API_KEY:-}"
      OPENAI_BASE_URL: "\${OPENAI_BASE_URL:-}"
      OPENAI_MODEL: "\${OPENAI_MODEL:-}"
    restart: unless-stopped
`;

const OPEN_HANDS_YAML = `\
services:
  openhands:
    image: ghcr.io/all-hands-ai/openhands:latest
    ports:
      - "127.0.0.1:3000:3000"
    environment:
      LLM_BASE_URL: "\${LLM_BASE_URL:-}"
      LLM_API_KEY: "\${LLM_API_KEY:-}"
      MODEL: "openrouter/deepseek/deepseek-v4-flash-0731"
    restart: unless-stopped
`;

const SERVICES: Record<ServiceId, ServiceInfo> = {
  opendesign: {
    image: "ghcr.io/nexu-io/od:latest",
    port: 7456,
    composeYaml: OPEN_DESIGN_YAML,
  },
  openhands: {
    image: "ghcr.io/all-hands-ai/openhands:latest",
    port: 3000,
    composeYaml: OPEN_HANDS_YAML,
  },
  fabric: {
    image: "github.com/connorodea/Fabric",
    port: 0,
    composeYaml: "",
  },
};

function serviceDir(id: ServiceId): string {
  return path.join(os.homedir(), ".local", "share", "sonyobs-services", id);
}

async function ensureComposeFile(id: ServiceId): Promise<string | null> {
  if (id === "fabric") return null;
  const dir = serviceDir(id);
  await fs.mkdir(dir, { recursive: true });
  const file = path.join(dir, "docker-compose.yml");
  await fs.writeFile(file, SERVICES[id].composeYaml, "utf8");
  return file;
}

function runDocker(args: string[], env: Record<string, string> = {}): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile("docker", args, { env: { ...process.env, ...env } }, (err, stdout, stderr) => {
      if (err) {
        reject(new Error(stderr.trim() || err.message));
        return;
      }
      resolve(stdout);
    });
  });
}

async function waitHealthy(port: number, timeoutMs: number = 30000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const connected = await connectOnce(port, 500);
      if (connected) return true;
    } catch {
      /* not up yet */
    }
    await sleep(1000);
  }
  return false;
}

function connectOnce(port: number, timeout: number): Promise<boolean> {
  return new Promise((resolve, reject) => {
    const socket = new net.Socket();
    socket.setTimeout(timeout);
    socket.once("connect", () => {
      socket.destroy();
      resolve(true);
    });
    socket.once("timeout", () => {
      socket.destroy();
      reject(new Error("timeout"));
    });
    socket.once("error", (err: Error) => {
      socket.destroy();
      reject(err);
    });
    socket.connect(port, "127.0.0.1");
  });
}

export class ManagedCompose {
  async status(id: ServiceId): Promise<ServiceStatus> {
    const info = SERVICES[id];
    if (id === "fabric") {
      try {
        const dir = serviceDir(id);
        const has = await exists(path.join(dir, ".git"));
        return {
          running: has,
          port: info.port,
          image: info.image,
          detail: has ? "clone present (start via Run)" : "not cloned",
        };
      } catch {
        return { running: false, port: info.port, image: info.image, detail: "not cloned" };
      }
    }
    try {
      const file = await ensureComposeFile(id);
      if (file === null) throw new Error("no compose file");
      const stdout = await runDocker(["compose", "-f", file, "ps", "--format", "json"]);
      const trimmed = stdout.trim();
      const running = trimmed !== "" && trimmed !== "[]";
      return { running, port: info.port, image: info.image, detail: running ? "up" : "stopped" };
    } catch (err) {
      return { running: false, port: info.port, image: info.image, detail: (err as Error).message };
    }
  }

  async up(id: ServiceId, env: Record<string, string> = {}): Promise<ServiceStatus> {
    const info = SERVICES[id];
    if (id === "fabric") {
      const dir = serviceDir(id);
      try {
        await fs.mkdir(dir, { recursive: true });
        if (!(await exists(path.join(dir, ".git")))) {
          await runGit(dir, ["clone", "--depth", "1", "https://github.com/connorodea/Fabric.git", "."]);
        }
        return { running: true, port: 0, image: info.image, detail: "cloned to " + dir };
      } catch (err) {
        return { running: false, port: 0, image: info.image, detail: (err as Error).message };
      }
    }
    try {
      const file = await ensureComposeFile(id);
      if (file === null) throw new Error("no compose file");
      const dockerEnv = { ...env };
      await runDocker(["compose", "-f", file, "up", "-d", "--remove-orphans"], dockerEnv);
      const healthy = await waitHealthy(info.port);
      return { running: healthy, port: info.port, image: info.image, detail: healthy ? "up" : "started; not yet healthy" };
    } catch (err) {
      return { running: false, port: info.port, image: info.image, detail: (err as Error).message };
    }
  }

  async down(id: ServiceId): Promise<void> {
    if (id === "fabric") return;
    try {
      const file = await ensureComposeFile(id);
      if (file !== null) await runDocker(["compose", "-f", file, "down", "--remove-orphans"]);
    } catch {
      /* best-effort */
    }
  }

  async downAll(): Promise<void> {
    for (const id of Object.keys(SERVICES) as ServiceId[]) {
      await this.down(id);
    }
  }
}

async function exists(p: string): Promise<boolean> {
  try {
    await fs.stat(p);
    return true;
  } catch {
    return false;
  }
}

function runGit(cwd: string, args: string[]): Promise<void> {
  return new Promise((resolve, reject) => {
    execFile("git", args, { cwd }, (err, _stdout, stderr) => {
      if (err) {
        reject(new Error(stderr.trim() || err.message));
        return;
      }
      resolve();
    });
  });
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
