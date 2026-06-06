# OBS Setup

This app does not modify OBS scenes' inner layout. It only:

* talks to OBS over WebSocket
* creates scenes by name
* switches between scenes
* starts / stops / pauses / resumes recording

You design each scene once in OBS. After that, everything is one CLI command away.

---

## 1. Install OBS Studio

* Download from <https://obsproject.com/>
* Open OBS once.
* macOS will prompt for **Screen Recording**, **Camera**, and **Microphone** permissions — accept all three. (System Settings → Privacy & Security if you missed it.)

## 2. Enable the OBS WebSocket server

`obs-websocket` ships built into OBS Studio 28+.

1. In OBS, open `Tools` → `WebSocket Server Settings`.
2. Check **Enable WebSocket server**.
3. Check **Enable Authentication**.
4. Set **Server Port** to `4455`.
5. Click **Generate Password** (or set your own).
6. Click **Show Connect Info** and copy the password.
7. Click **OK**.

Paste that password into `.env`:

```
OBS_PASSWORD=<paste here>
```

## 3. Pick or set the recording output folder

`Settings` → `Output` → `Recording` → `Recording Path`.

Set it to the folder you put in `config.yaml` under `recording_root`. Default:
`~/Movies/OBS_Recordings`.

Recommended:

* **Recording Format**: `MKV` (safer if OBS crashes) or `MP4` (more portable)
* **Encoder**: hardware (`Apple Silicon` on Apple Silicon Macs)
* **Audio Track**: at least track 1 for mic

## 4. Add the sources

Add these as inputs in OBS. The **source name in OBS must exactly match** the value
in `config.yaml` (case-sensitive).

| What                  | OBS Source Type           | Default name in `config.yaml`   |
| --------------------- | ------------------------- | ------------------------------- |
| Sony camera           | **Video Capture Device**  | `Sony Camera`                   |
| MacBook camera        | **Video Capture Device**  | `MacBook Camera`                |
| Microphone            | **Audio Input Capture**   | `Microphone`                    |
| Screen                | **macOS Screen Capture**  | `Screen Capture`                |

To add: in OBS, with any scene selected, click the `+` under **Sources** and pick the type.
When you create the source, type the name listed above.

If you already named them differently, just edit `sources:` in `config.yaml`.

## 5. Create the scenes

Easiest path: run

```bash
uv run recording-auto scenes bootstrap
```

This creates these scenes if missing:

* `Talking Head`
* `Screen Tutorial`
* `Dual Camera`
* `Screen + Camera`

Then open OBS, click each scene, and drop the sources into it:

| Scene             | Layout                                                              |
| ----------------- | ------------------------------------------------------------------- |
| Talking Head      | `Sony Camera` full-frame + `Microphone`                             |
| Screen Tutorial   | `Screen Capture` full-frame + `Microphone`                          |
| Dual Camera       | `Sony Camera` full-frame + `MacBook Camera` corner PIP + `Microphone` |
| Screen + Camera   | `Screen Capture` full-frame + `Sony Camera` corner PIP + `Microphone` |

In OBS, *sources can be referenced by multiple scenes* — drag the existing source from the
**Sources** panel of another scene (the dialog asks "Add Existing" vs "Create New").

## 6. Verify

```bash
uv run recording-auto doctor
```

Every row should say `pass`.

If a `fail` row shows up, the `hint` column tells you the fix.
