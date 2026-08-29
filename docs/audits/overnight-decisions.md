# Overnight decisions — 2026-08-28/29

## D1. Integrate connorodea/Fabric as an AI-Edit backend. in scope this window.

- **Decision:** Wire fabric. Connor's fork. into the Electron app's AI Edit lane as an optional pattern-execution backend, alongside OpenRouter, OpenHands, OpenDesign,, Cutroom. Shipped once scaffold builds. MVP: clone his fork into ~/.local/share/sonyobs-services/fabric, expose start/stop/status via the services IPC slot, wire a "Run fabric pattern" input into the Edit tab..

- **Options:**.a. skip Fabric to M2. .b. full integrate now...)

- **Chosen default + why:** integrate now, minimal surface. His explicit ask. "integrate this into it too". Fabric's pattern library directly feeds the AI-edit/video-production goal,, it needs no new deps. clone + subprocess., and a private fork avoids public-upstream drift..

- **Reversal cost:** one feature branch, a services entry; flip a setting toggle,, undo = toggle off, no code loss...

