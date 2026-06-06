# Sony Camera Setup (RX100 focus)

This app supports any Sony body that appears to macOS as a camera. The RX100
family is the reference target. There are three reliable ways to get the
camera into OBS on macOS. Pick whichever you have hardware for.

---

## Option A — HDMI out into a capture card  (works for every RX100)

You need a capture card: Elgato Cam Link 4K, Magewell HDMI to USB, AVerMedia
Live Gamer, etc.

1. **Use a micro-HDMI → HDMI cable** out of the camera.
2. In camera menu, enable **clean HDMI output**:
    * RX100 V/VI/VII: `MENU → Setup → HDMI Settings → HDMI Info. Display → Off`
3. **Disable auto power off**: `MENU → Setup → Power Save Start Time → Off` (or 30 min if Off isn't there).
4. **Set the camera to video mode** and pick the resolution/frame rate you want OBS to record (1080p60 is a good default).
5. **Autofocus**: `Focus Mode → AF-C` for video.
6. **Use external power**: USB-C power adapter, or a Sony "AC-PW20" dummy battery. The internal battery won't last a long session.
7. Plug HDMI → capture card → MacBook USB-C.
8. In OBS, add **Video Capture Device** → pick the capture card. Name the source `Sony Camera` (or whatever matches `config.yaml`).
9. Run:

   ```bash
   uv run recording-auto sony scan
   uv run recording-auto sony connect
   ```

   You should see the capture card in the scan and a green "Connected" message from connect.

---

## Option B — USB Streaming  (RX100 VI and VII)

Newer RX100 bodies do UVC over USB-C natively.

1. `MENU → Network → USB Streaming → On`
2. Connect USB-C cable to MacBook.
3. The camera screen will show "Streaming Standby" → start streaming.
4. In OBS, add **Video Capture Device** → pick "ILCE-…" / "DSC-RX100…". Name it `Sony Camera`.
5. Run:

   ```bash
   uv run recording-auto sony scan
   uv run recording-auto sony connect
   ```

---

## Option C — Sony "Imaging Edge Webcam"  (older RX100 II/III/IV/V)

Sony's official webcam helper makes the camera appear as a UVC source.

1. Download **Imaging Edge Webcam** for macOS:
   <https://support.d-imaging.sony.co.jp/app/webcam/en/>
2. Install it (it's a System Extension — you may need to approve it in System Settings → Privacy & Security → "Allow").
3. Plug the camera in via USB.
4. Power on the camera and start the Webcam helper if it isn't running.
5. In OBS, add **Video Capture Device** → pick "Sony Camera (Imaging Edge)". Name the OBS source `Sony Camera`.
6. Run `uv run recording-auto sony scan` to confirm detection.

> Note: Imaging Edge Webcam runs at 1024×576 in v1; for full HD you need the HDMI capture card path.

---

## Recommended camera settings for video

* Format: `XAVC S` / `MP4` (the camera's own recording is separate from OBS)
* Frame rate: 60p (or 30p if you need long takes)
* Focus mode: `AF-C` with `Wide` or `Center` area
* Steady shot: `Active`
* Picture profile: any neutral profile (e.g. `PP1` or off for SDR)
* White balance: pick `K` and set it (don't leave on Auto if you switch lighting)
* ISO: `Auto` with a cap (e.g. `ISO 100–3200`)

## Power

For anything over 20–30 min you want external power:

* USB-C power adapter (RX100 VI/VII supports USB-C powering while recording)
* Or a Sony AC-PW20 dummy battery + AC-LS5 adapter

## Lens / overheat

* RX100 series can overheat under long 4K runs. Stick to 1080p60 for long sessions.
* Open the camera body battery door to vent if needed.
