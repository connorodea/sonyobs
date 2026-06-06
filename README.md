# mac_sony_obs_recording_automation

A local-first macOS automation tool that drives **OBS Studio** to record video from a
**Sony camera** (RX100 family or similar), the **MacBook camera**, a **microphone**,
and the **screen** — from a one-line CLI or a small local HTTP API.

* No cloud. No accounts. No GUI.
* OBS owns the encoder, the file format, and the file path. This app only orchestrates.
* All OBS calls go through `obs-websocket` on `localhost:4455`.

---

## What this tool does

After install you can call it from any directory. Three names all do the same thing:

| Command          | Notes                          |
| ---------------- | ------------------------------ |
| `sonyobs`        | Primary name.                  |
| `sob`            | Two-letter alias.              |
| `recording-auto` | Spec name.                     |

The most useful commands:

* `sonyobs go` — **one-keystroke**: switch to the default profile's scene, start recording, attach a live dashboard. Ctrl+C to stop.
* `sonyobs go --for 5m` — record for exactly 5 minutes, auto-stop.
* `sonyobs go --detached` — start and return immediately (no dashboard).
* `sonyobs watch` — attach the live dashboard to whatever OBS is already recording.
* `sonyobs stop` — stop recording.
* `sonyobs clip "intro-take-3"` — stop AND rename the last file with a label.
* `sonyobs recent` — list the most recent recordings with size + age.
* `sonyobs doctor` — prove the whole pipeline works before you press record.
* `sonyobs sony scan` / `sony connect` — find the RX100 and bind it to OBS.
* `sonyobs scenes bootstrap` — create the OBS scenes the profiles expect.
* `sonyobs start -p screen_tutorial` — explicit profile selection (no dashboard).
* `sonyobs pause` / `resume` / `status` (add `--json` for machine output).
* `sonyobs api` — local FastAPI server with the same controls over HTTP.

The `go`, `watch`, `stop`, and error paths fire **native macOS notifications**
(silenceable with `--no-notify`). Anything that hits OBS over WebSocket shows
a **dots spinner** while it connects.

---

## Required hardware

* MacBook Pro (Apple Silicon or Intel)
* **Sony camera**, any of:
  * RX100 VI / VII (built-in USB Streaming — recommended)
  * Older RX100 (II / III / IV / V) via [Sony Imaging Edge Webcam](https://support.d-imaging.sony.co.jp/app/webcam/en/)
  * Any Sony body via HDMI out + capture card (Elgato Cam Link, Magewell, AVerMedia, etc.)
* Optional: external microphone (USB or via audio interface)
* Optional: built-in MacBook camera

---

## Install

### 1. Install OBS Studio

Download from <https://obsproject.com/> and open it once so it can request screen / camera / mic permission.

### 2. Enable the OBS WebSocket

In OBS:

1. `Tools` → `WebSocket Server Settings`
2. Check **Enable WebSocket server**
3. Set **Server Port** to `4455`
4. Set a **Server Password** and copy it

(Full walkthrough: [`docs/OBS_SETUP.md`](docs/OBS_SETUP.md))

### 3. Install this tool with `uv`

```bash
# from the repo root
./scripts/install.sh
```

What that does:

* installs [`uv`](https://docs.astral.sh/uv/) if missing
* `uv sync` to create `.venv` and install dependencies
* `uv tool install .` — installs `sonyobs`, `sob`, and `recording-auto` into `~/.local/bin/` so you can call them from any directory
* copies `.env.example` → `.env`
* copies `config.example.yaml` → `config.yaml`

> Make sure `~/.local/bin` is on your `PATH`. uv usually handles this; if `which sonyobs` returns nothing, add `export PATH="$HOME/.local/bin:$PATH"` to your `~/.zshrc`.

### 4. Configure

Edit `.env` and put your real OBS WebSocket password:

```
OBS_HOST=localhost
OBS_PORT=4455
OBS_PASSWORD=<paste from OBS here>
```

Edit `config.yaml` so the `sources:` block matches the OBS input names you'll create:

```yaml
sources:
  sony_camera: "Sony Camera"        # match this in OBS exactly
  macbook_camera: "MacBook Camera"
  microphone: "Microphone"
  screen_capture: "Screen Capture"
```

### 5. Add the OBS sources

In OBS, in any scene, click `+`:

| Source                | OBS Type              | Name (must match config.yaml) |
| --------------------- | --------------------- | ----------------------------- |
| Sony RX100            | Video Capture Device  | `Sony Camera`                 |
| MacBook camera        | Video Capture Device  | `MacBook Camera`              |
| Microphone            | Audio Input Capture   | `Microphone`                  |
| Screen                | macOS Screen Capture  | `Screen Capture`              |

(Step-by-step Sony setup: [`docs/SONY_CAMERA_SETUP.md`](docs/SONY_CAMERA_SETUP.md).)

### 6. Verify

```bash
sonyobs doctor
```

You want every check `pass`. If anything fails, the `hint` column tells you the exact fix.

---

## Daily use

```bash
# the fast path — attaches a live dashboard; Ctrl+C stops cleanly
sonyobs go

# record for exactly 5 minutes, auto-stop, label the file "demo"
sonyobs go --for 5m
sonyobs clip demo

# different profile, no dashboard
sonyobs start -p screen_tutorial
sonyobs stop

# attach the dashboard to a recording that's already running
sonyobs watch

# pause / resume / status / browse old files
sonyobs pause
sonyobs resume
sonyobs status
sonyobs recent
sonyobs status --json   # for scripting

# Sony RX100 helpers
sonyobs sony scan
sonyobs sony connect

# scenes
sonyobs scenes bootstrap
sonyobs scenes list
```

### The live dashboard

When you run `sonyobs go` (without `--detached`), you get a Rich `Live`
panel that polls OBS twice a second and shows:

* `● REC` / `⏸ PAUSED` state with color
* the OBS timecode (HH:MM:SS)
* the current scene + profile
* total bytes written and a rolling write rate (MB/s)
* a remaining countdown if you used `--for`

Ctrl+C stops the recording and gives you a "recording finished" summary
with the output path, duration, and stop reason.

### Available profiles (from `config.yaml`)

| Profile              | Scene             | Layout                                                        |
| -------------------- | ----------------- | ------------------------------------------------------------- |
| `talking_head`       | Talking Head      | Sony camera full-frame + mic                                  |
| `screen_tutorial`    | Screen Tutorial   | Screen capture full-frame + mic                               |
| `dual_camera`        | Dual Camera       | Sony primary + MacBook camera picture-in-picture              |
| `screen_plus_camera` | Screen + Camera   | Screen primary + Sony camera picture-in-picture               |

You design the layout *once* inside each OBS scene; this tool just switches between them.

---

## Sony RX100 quick connect

```bash
# Lists every camera-like device the Mac sees, flags Sony / RX100 / capture cards.
sonyobs sony scan

# Finds the RX100 and matches it to the OBS input named in config.sources.sony_camera.
sonyobs sony connect

# Force a specific OBS input name (skips matching):
sonyobs sony connect --obs-source "Sony RX100 (HDMI)"
```

How the detection works:

1. `system_profiler SPCameraDataType` — finds UVC / FaceTime / capture devices
2. `system_profiler SPUSBDataType` — finds Sony USB devices by vendor ID `0x054c`
3. AVFoundation (if PyObjC is available) — for clean device names

If the RX100 doesn't show up, see the troubleshooting guide.

---

## Local HTTP API

```bash
sonyobs api                        # http://127.0.0.1:8765
# Interactive docs at: http://127.0.0.1:8765/docs
```

| Method | Path                | Body                       |
| ------ | ------------------- | -------------------------- |
| GET    | `/health`           | —                          |
| GET    | `/status`           | —                          |
| GET    | `/scenes`           | —                          |
| GET    | `/sources`          | —                          |
| GET    | `/sony/scan`        | —                          |
| POST   | `/sony/connect`     | optional `?obs_source=`    |
| POST   | `/recording/start`  | `{"profile": "talking_head"}` |
| POST   | `/recording/stop`   | —                          |
| POST   | `/recording/pause`  | —                          |
| POST   | `/recording/resume` | —                          |

Example:

```bash
curl -s http://127.0.0.1:8765/health | jq
curl -s -X POST http://127.0.0.1:8765/recording/start \
     -H 'content-type: application/json' \
     -d '{"profile": "talking_head"}'
```

---

## HDMI capture card setup

* Set the camera to **clean HDMI output** (no overlays, no autofocus boxes).
* Plug the HDMI out → capture card → MacBook USB-C.
* In OBS, add a **Video Capture Device** and pick the capture card. Rename the source `Sony Camera`.

(Full guide: [`docs/SONY_CAMERA_SETUP.md`](docs/SONY_CAMERA_SETUP.md).)

## USB webcam mode setup

* RX100 VI / VII: `MENU → Network → USB Streaming → On`, plug in USB-C, the camera shows up as a UVC device.
* Older RX100: install [Imaging Edge Webcam](https://support.d-imaging.sony.co.jp/app/webcam/en/), plug in USB.
* Disable auto power off (`Power Save Start Time → Off`).
* Use a USB-C power adapter or dummy battery for long sessions.

---

## Troubleshooting

See [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) for:

* `OBS WebSocket not reachable`
* `OBS auth failed`
* `Sony Camera missing from sources`
* recordings save in the wrong folder

---

## Development

```bash
uv sync
uv run pytest -q
```

Tests don't require OBS to be installed — the OBS client is mocked.

---

## Layout

```
src/recording_automation/
  __init__.py
  main.py            # `python -m recording_automation`
  cli.py             # Typer CLI
  config.py          # Pydantic config models
  obs_client.py      # obsws-python wrapper
  scenes.py          # scene bootstrapper + switcher
  sources.py         # source listing + verification
  profiles.py        # profile lookup
  recording.py       # start/stop/pause/resume orchestration
  health.py          # `doctor` checks
  api.py             # FastAPI server
  sony_camera.py     # RX100 detection / quick-connect
  utils.py
scripts/
  install.sh
  run_cli.sh
  run_api.sh
tests/
  test_config.py
  test_profiles.py
  test_health.py
docs/
  OBS_SETUP.md
  SONY_CAMERA_SETUP.md
  TROUBLESHOOTING.md
```

---

## License

MIT.
