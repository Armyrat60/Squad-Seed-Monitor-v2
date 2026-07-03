# Squad Seed Monitor v2 — build handoff

## What this is
A full rewrite of the seeding tool into a modern, distributable desktop app.
Split into `core.py` (all logic, no GUI — unit-tested headless) and `app.py`
(CustomTkinter GUI). Config/favorites persist to `seed_monitor_config.json`;
actions are logged to `seed_monitor.log`.

## Before first release — set these
In `core.py`:
```python
GITHUB_OWNER = "YOUR_GITHUB_USERNAME"   # your fork's owner
GITHUB_REPO  = "Squad-Seed-Monitor"     # your fork's repo name
```
Until set, the update checker safely does nothing.

## Feature set
- Server search (BattleMetrics by name) or paste ID; connect auto-filled.
- Seed-layer gate using BattleMetrics `details.gameMode` ("Seed"), with map-name
  keyword fallback. Only fires while seeding; auto-reverts when server goes live.
- Full reversibility: mute/unmute toggle, apply/restore graphics, one-click Undo
  All, and automatic revert on target-hit or live-layer transition.
- Shutdown safety: confirm dialog (fail-safe to cancel if ignored) + abortable
  grace window + auto-abort on quit. Min-uptime guard.
- Tabs: Monitor / Favorites / Settings / Log.
- Favorites (save/switch servers), full Settings panel, log viewer.
- Live player-count graph (native canvas, no matplotlib).
- System tray (minimize/restore/quit) and desktop notifications — both optional
  and graceful if libs are absent.
- Update checker (GitHub Releases, notify + link).

## Tested (headless, in CI-like env)
All of `core.py`: config defaults/persistence, real BM payload parse, seed gate,
connect override, favorites, semver update logic, player-history buffer, and
graceful fallback when optional deps are missing. Plus modeled state machines for
the shutdown-confirm fail-safe, auto-revert transitions, mute toggle, and
tray/quit decisions. Both modules compile; all CustomTkinter widgets used are
confirmed present in ctk 6.0.0.

## NEEDS testing on a real Windows machine (can't verify headless)
1. GUI renders correctly (all four tabs, graph draws, layout).
2. **System tray** — minimize to tray, click icon to restore, right-click Quit.
   This is the highest-risk item (pystray + CustomTkinter dual event loop).
3. Desktop notifications actually pop (requires `plyer`).
4. Shutdown confirm dialog appears and the countdown auto-cancels.
5. `pyinstaller seedmon.spec` produces a working exe that launches (the
   CustomTkinter data-file bundling is handled in the spec, but verify).
6. Direct-connect lands on the server (confirmed port 10215 is the game port).

## Build / release
- Local: `pyinstaller seedmon.spec` -> `dist/SquadSeedMonitor.exe`
- Auto: push a `vX.Y.Z` tag -> GitHub Actions builds and publishes a release.
  Bump `__version__` in `core.py` to match the tag each release.
