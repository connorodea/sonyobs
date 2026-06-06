# Troubleshooting

Run this first:

```bash
uv run recording-auto doctor
```

Every check has a `hint` column. The mapping below covers the most common failures.

---

## `OBS WebSocket reachable: fail`

Cause: OBS isn't open, the WebSocket server is off, or the port is wrong.

Fix:
1. Open OBS.
2. `Tools` → `WebSocket Server Settings`.
3. Tick **Enable WebSocket server**, port `4455`.
4. Confirm `OBS_HOST=localhost` and `OBS_PORT=4455` in `.env`.

If it still fails:

```bash
lsof -i :4455
```

Should show `obs` listening. If it doesn't, OBS isn't listening yet.

---

## `OBS WebSocket reachable: fail` with "auth" in detail

The OBS WebSocket password in `.env` doesn't match OBS.

Fix:
1. `Tools` → `WebSocket Server Settings` → `Show Connect Info` → copy `Server Password`.
2. Paste into `.env` as `OBS_PASSWORD=…`.
3. Save `.env`. Re-run `recording-auto doctor`.

---

## `OBS sources present: fail — missing: Sony Camera, Microphone`

OBS has no input matching the names in `config.yaml`.

Two options:

**Option A**: add the missing inputs in OBS using the exact names.
* In OBS, `+` under Sources → `Video Capture Device` → name it `Sony Camera`.
* `+` → `Audio Input Capture` → name it `Microphone`.

**Option B**: update `config.yaml` to whatever names you already use:

```yaml
sources:
  sony_camera: "My RX100 over HDMI"
  microphone: "Rode NT-USB Mini"
```

---

## `OBS scenes present: fail — missing: Talking Head`

Run:

```bash
uv run recording-auto scenes bootstrap
```

This creates any scene named in your profiles. Then arrange sources inside each scene in OBS.

---

## `recording_root writable: fail`

The folder you set in `config.yaml` either doesn't exist or isn't writable.

Fix:
* Edit `config.yaml` → set `recording_root` to a writable folder, e.g. `~/Movies/OBS_Recordings`.
* Make sure OBS has macOS **Full Disk Access** if you're writing outside the user folder.

---

## `sony scan` shows no devices

* Confirm the camera is **powered on** and not in playback / menu mode.
* Confirm the cable is **USB data**, not power-only.
* RX100 VI/VII: `MENU → Network → USB Streaming → On`.
* Older RX100: install **Imaging Edge Webcam** (see `SONY_CAMERA_SETUP.md`).
* Or check that the HDMI capture card shows up as a USB camera:

   ```bash
   system_profiler SPCameraDataType
   system_profiler SPUSBDataType | grep -i sony
   ```

---

## `sony connect` says "Detected camera 'X', but OBS has no input"

You're seeing the camera at the OS level, but OBS doesn't have an input for it yet.

Fix:
1. In OBS, `+` under Sources → `Video Capture Device`.
2. Pick the device whose name matches what `sony scan` reported.
3. Name the OBS source `Sony Camera` (or whatever `config.yaml`'s `sources.sony_camera` says).
4. Re-run `sony connect`.

---

## Recordings save in the wrong folder

`recording_root` in `config.yaml` doesn't actually change where OBS saves files —
it's the folder this tool uses for date-organized index folders. The real output
folder is set in OBS:

`Settings` → `Output` → `Recording` → `Recording Path`.

Set those to the same folder so they stay in sync.

---

## "Cannot pause" / "Cannot resume"

You can only pause an active recording, and you can only resume a paused one.
Run `recording-auto status` to see the real state.

Also: not every encoder supports mid-stream pause. If your OBS Output is set to
"Use stream encoder", the pause command may be ignored. Switch the encoder to a
record-specific one (`Settings → Output → Recording → Encoder`).

---

## `uv` is not installed

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
exec $SHELL
```

Then re-run `./scripts/install.sh`.

---

## Tests fail with `ModuleNotFoundError: recording_automation`

You're probably running `pytest` outside the `uv` venv. Use:

```bash
uv run pytest -q
```

(The `tests/conftest.py` adds `src/` to `sys.path`, so it works without an editable install — but the dependencies still need to come from `uv sync`.)
