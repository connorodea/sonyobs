# SonyOBS Studio — Electron Desktop App + AI Video Production (Architecture Plan)

Status: DRAFT — synthesized from 20 parallel DeepSeek research agents + codebase audit, 2026-08-28.

## 1. Decision summary

| Decision | Choice | Why |
|---|---|---|
| App shell | **Electron** (main/preload/renderer, electron-vite + electron-builder) | Requested; wraps existing Python core |
| Capture backend | **Keep Python sidecar** (FastAPI on 127.0.0.1, random bearer token) | Porting Sony SDK + OBS logic to Node is costly/error-prone (sidecar report verdict) |
| Video edit engine | **Cutroom** (Connor's existing repo: SDK / MCP server / CLI / Hono server / agent planner) | Already built; reuse over reimplement |
| Lightweight render/export | **editly** (Node, drives FFmpeg) in a utilityProcess worker | Fast scripted cuts, captions, concat |
| Transitions/generators | **FFmpeg xfade + preset JSON model** | Declarative, battle-tested |
| Static assets | **ImageMagick** (`magick` CLI via execFile) | Title cards, lower-thirds, gradients, overlays |
| Transcript→edit | **Whisper (local) or Deepgram (key)** → transcript JSON → LLM → **EDL JSON** → FFmpeg render | Descript has no public API (refuted); DaVinci requires GUI + is not a substitute (report verdicts) |
| AI agents | **OpenRouter (user key) + Claude Code CLI + Codex CLI** via a unified "AI Edit" panel | User requirement |
| OpenDesign | **Docker sidecar** at `~/.local/share/open-design` (already installed), shown in a **WebContentsView**, driven with the user's OpenRouter key | No connorodea fork exists; native embedding not documented (report) |
| OpenHands | **No connorodea fork exists** — use upstream. Integrate via **openhands-agent-sdk** (Python REST server on 127.0.0.1) or Docker | Report refuted the "11-year-old" premise; MIT, feasible |
| ACP | **Thin ACP adapter** in main process routes AI-Edit to any backend | Protocol connects editors to agents |
| Job orchestration | **Main-process JobManager** (DAG + queue, concurrency 2–4) with `utilityProcess` workers | Report verified this shape |
| Packaging | electron-builder (dmg/zip) + PyInstaller sidecar + ffmpeg-static + bundled docker-compose for OpenDesign | macOS report |

## 2. Process tree

```text
BrowserWindow (renderer, sandboxed, contextIsolation on)
   ⇅ contextBridge/preload (window.sonyobs API)
Main Process (orchestrator, JobManager, IPC, key storage safeStorage)
   ├─ utilityProcess: job worker pool (FFmpeg/editly/ImageMagick)
   ├─ utilityProcess: agent worker (Claude Code / Codex CLI)
   ├─ child_process: python sidecar (FastAPI, 127.0.0.1:<port>, bearer token) ← existing sonyobs core
   ├─ child_process: ffmpeg-static (via workers)
   ├─ child_process: docker compose up (OpenDesign, 127.0.0.1:7456)
   ├─ child_process: openhands-agent-sdk server (127.0.0.1:<port>) [optional]
   └─ network: OpenRouter API, Sony camera API, Cutroom worker API
```

Security: contextIsolation on, sandbox on, no nodeIntegration, strict CSP in renderer,
API key via Electron `safeStorage` (never in renderer), subprocess args passed as
arrays to `execFile`/`spawn` (never shell strings), local sidecars bound to 127.0.0.1 only.
WebContentsView for OpenDesign (no `<webview>` tag).

## 3. Repo layout (in this repo, `electron/`)

```text
electron/
  package.json            # electron-vite + electron-builder, entrypoints
  electron.vite.config.ts
  src/main/index.ts       # app lifecycle, window, JobManager, sidecar spawn
  src/main/JobManager.ts  # DAG queue, retry, IPC events
  src/main/Sidecar.ts     # python sidecar spawn/health/restart
  src/main/openrouter.ts  # OpenRouter client (SSE, safeStorage key)
  src/main/mcpServer.ts   # video-editing tools for Claude Code / Codex
  src/main/acp.ts         # ACP adapter (OpenRouter/OpenHands/Claude/Codex)
  src/main/openDesign.ts  # docker compose up/down + WebContentsView
  src/main/cutroom.ts     # CutroomClient wrapper (SDK/MCP/CLI)
  src/main/presets.ts     # transition/generator preset model (FFmpeg xfade)
  src/main/assets.ts      # ImageMagick asset recipes
  src/main/edl.ts         # EDL JSON schema + validator
  src/preload/index.ts
  src/renderer/ ...       # UI: Capture, Timeline/EDL, AI Edit, Agents, OpenDesign tab, Settings
```

Cutroom itself stays a separate repo; this app depends on `@cutroom/sdk` + the `cutroom` CLI.

## 4. AI Edit panel routing (ACP)

One panel, four backends selectable by the user:

- **OpenRouter**: main-process chat/completions SSE with tool-calling (`apply_edit`, `generate_asset`),
  default model `deepseek/deepseek-v4-flash-0731`.
- **Claude Code**: spawn `claude -p` with `--mcp-config` pointing at this app's local MCP server
  (tools: `timeline.read`, `timeline.edit`, `video.render`, `video.export`).
- **Codex**: spawn `codex exec --json` (custom base URL → OpenRouter supported) with same tools.
- **OpenHands / OpenDesign**: local SDK server / docker sidecar.

## 5. EDL → render pipeline

1. Import/record → FFmpeg extract audio (16 kHz mono).
2. Transcribe: faster-whisper (local) or Deepgram (user key).
3. LLM (OpenRouter) proposes edit decisions from transcript JSON → **EDL**:
   `{version, source, operations[]}` (cut/keep/emphasis/b-roll/lower-third with time bounds).
4. Validator clamps timestamps to transcript bounds.
5. Render: resolve EDL operations → FFmpeg concat + xfade + drawtext/overlay + acrossfade.

Cutroom already implements much of this (clean-up, transcript-cut, captions, highlights,
overlay, reframe, create). Priority: reuse Cutroom API for transcript-driven edits; add
editly + presets for local light-duty and to avoid a worker round-trip.

## 6. Milestones

- **M1 Scaffold**: Electron shell + python sidecar spawn + Settings (OpenRouter key, safeStorage) + Capture tab (existing /health, /status, /recording/*, /sources, /scenes, /sony/*).
- **M2 Cutroom + EDL**: cutroom wrapper, local EDL engine, transcript→edl→FFmpeg render, timeline view.
- **M3 Agents**: OpenRouter client + AI Edit panel, Claude Code + Codex MCP wiring, OpenDesign docker/WebContentsView.
- **M4 OpenHands (IN SCOPE this session)**: agent-sdk sidecar integration + AI panel routing (Connor: "don't defer openhands", 2026-08-28).
- **M5 Packaging**: electron-builder dmg + PyInstaller sidecar; keep `sonyobs menubar` + CLI intact.

## 7. Open items / decisions for Connor

- Scope cut for M1 (see questions).
- OpenHands: which image/tag + OpenRouter model routing; or defer.
- OpenDesign: always-on sidecar vs on-demand launch.
- Which video engine path for v1: Cutroom API vs local editly/FFmpeg.
---

## Research batch results (appended post-run)

- 18/20 succeeded; 2 timeout after 2 attempts: **acp-adapter**, **electron-security**.
- Refutes to honor: Descript (no public API — use Whisper/Deepgram + EDL/ffmpeg), OpenHands "11-year" premise (founded 2024).
- Environment verified: Node 24.11, pnpm 10.33, Docker up, ffmpeg 9.0.1, Python 3.13.
- Forks: NO OpenHands or OpenDesign fork under connorodea → use upstream both.
- OpenDesign: local checkout already at ~/.local/share/open-design + claude-design launcher manages docker compose on 127.0.0.1:7456.
