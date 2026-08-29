import { spawn, ChildProcess } from "node:child_process";
import { EventEmitter } from "node:events";

export interface SidecarOptions {
  cmd: string;
  args: string[];
  cwd: string;
  portEnv?: string;
  port?: number;
}

const DEFAULT_PORT = 8765;
const MAX_RESTART_DELAY = 15000;

/**
 * Manages the Python FastAPI sidecar (the existing sonyobs core).
 * Binds to 127.0.0.1 on a chosen port, health-checks it,
 * and restarts it with exponential backoff if it dies.

 **/
export class Sidecar extends EventEmitter {
  readonly port: number;
  private readonly opts: SidecarOptions;
  private proc: ChildProcess | null = null;
  private stopped = false;
  private attempts = 0;
  private readonly args: string[];

  constructor(opts: SidecarOptions) {
    super();
    this.opts = opts;
    this.port = opts.port ?? DEFAULT_PORT;
    this.args = [...opts.args];
    if (opts.portEnv) {
      this.args.push("--port", String(this.port));
    }
  }

  start(): void {
    if (this.proc) return;
    this.stopped = false;
    this.launch();
  }

  private launch(): void {
    const env = {
      ...process.env,
      PYTHONUNBUFFERED: "1",
    };

    this.proc = spawn(this.opts.cmd, this.args, {
      cwd: this.opts.cwd,
      env,
      stdio: ["ignore", "pipe", "pipe"],
    });

    this.proc.stdout?.on("data", (chunk: Buffer) => log(`[sidecar] ${chunk.toString().trimEnd()}`));
    this.proc.stderr?.on("data", (chunk: Buffer) => logErr(`[sidecar] ${chunk.toString().trimEnd()}`));

    this.proc.on("error", (err: Error) => {
      logErr(`sidecar spawn error: ${err.message}`);
      this.emit("state", "error");
    });

    this.proc.on("exit", (code: number | null) => {
      logErr(`sidecar exited (${code}); stopped=${this.stopped}`);
      this.proc = null;
      if (this.stopped) return;

      const delay = Math.min(1000 * 2 ** this.attempts, MAX_RESTART_DELAY);
      this.attempts += 1;
      this.emit("state", "restarting");
      setTimeout(() => this.launch(), delay);
    });

    this.emit("state", "starting");
    void this.waitHealthy();
  }

  private async waitHealthy(): Promise<void> {
    const deadline = Date.now() + 20000;
    while (Date.now() < deadline) {
      try {
        const res = await fetch(`http://127.0.0.1:${this.port}/health`);
        if (res.ok) {
          this.attempts = 0;
          this.emit("state", "healthy");
          return;
        }
      } catch (err) {
        // not up yet
      }
      await sleep(500);
    }
    logErr("sidecar healthcheck timed out");
    this.emit("state", "unhealthy");
  }

  stop(): void {
    this.stopped = true;
    if (this.proc) {
      this.proc.kill("SIGTERM");
      const proc = this.proc;
      setTimeout(() => proc.kill("SIGKILL"), 3000).unref();
    }
  }
}

function log(msg: string): void {
  if (process.env.ELECTRON_DEBUG) console.log(msg);
}

function logErr(msg: string): void {
  console.error(msg);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}