# Squad Seed Monitor

A desktop helper for Squad players who **seed** servers — sit in an empty server
at low graphics/FPS to help it populate. It watches a BattleMetrics server and,
once the server is genuinely seeded, returns your game to normal (and optionally
closes Squad or shuts down your PC) so you don't have to babysit it.

## Download & install

1. Go to the [**Releases**](../../releases) page and download the latest
   `SquadSeedMonitor.exe`.
2. Double-click it. That's it — no installer, no Python needed.

> **"Windows protected your PC" / SmartScreen warning?**
> This is expected. The app is free and unsigned (code-signing certificates cost
> money), and because it can close programs and shut down the PC, Windows flags
> unknown apps that do this. To run it: click **More info → Run anyway**.
> If you'd rather not, you can run from source instead (see below) — same app,
> no warning, and you can read every line of the code.

## What it does

- **Find your server** — search BattleMetrics by name or paste a server ID. The
  connect address is pulled automatically.
- **Seed-layer aware** — it knows when the server is on a *seeding* layer (via
  BattleMetrics' game mode) and only acts while seeding. When the map rotates to
  a live layer, it automatically returns your game to normal so you can play.
- **Returns your game to normal automatically** — unmutes and restores your
  graphics settings when seeding is done (target reached or server goes live).
  Nothing to remember to undo.
- **Safe shutdown** — if you choose "Shutdown PC", it asks you to confirm first,
  gives an abortable countdown, and cancels automatically if you don't respond.
- **Favorites dashboard** — save the servers you seed and see them all at a
  glance: each shows live player count and whether it's **Seeding**, **Live**, or
  **Empty**, auto-refreshing while the app is open. Switch to any of them in one
  click. A ☆/★ next to the current server on every tab toggles it as a favorite.
- **Live graph, tray, notifications** — watch the population climb, minimize to
  the system tray, and get a desktop toast when the server is seeded.
- **Update check** — tells you when a newer version is available.

## How to use

1. **Search your server** (name or BM ID) and select it.
2. **Set your target** — the population at which seeding is "done" (default 95).
   Leave **Only fire on seed layer** on; it's the safest signal.
3. Click **Apply** (low res/FPS) with Squad **closed**, then click **Connect** —
   with Squad closed it launches the game *and* joins the server (wait through
   the loading screens; don't click during them). The server address is also
   copied to your clipboard. If Squad is already open, or it lands on the main
   menu, paste that address into the in-game **Custom Browser**, or use the
   **SquadBrowser** button ([squadbrowser.app](https://squadbrowser.app/)).
   (Steam's own direct-connect has been broken for Squad since 2023 — a Valve
   bug — so the in-game/web browser is the reliable path.)
4. Pick what happens when seeded: **Do Nothing** / **Kill Process** / **Shutdown PC**.
5. Walk away. When the server seeds or goes live, your game is restored
   automatically (and Squad closes / PC shuts down if you chose that).

First time, run with **Do Nothing** and watch it reach target once to see how it
behaves before using Shutdown.

## Run from source (no SmartScreen warning)

```bash
pip install -r requirements.txt
python app.py
```

Windows only. `plyer` (notifications), `pystray`/`Pillow` (tray) are optional —
the app runs fine without them, just without those features.

## Build the exe yourself

```bash
pip install -r requirements.txt
pyinstaller seedmon.spec
# -> dist/SquadSeedMonitor.exe
```

Releases are also built automatically by GitHub Actions when a `v*` tag is
pushed (see `.github/workflows/build-release.yml`).

## Files it creates

In a stable per-user folder — `%LOCALAPPDATA%\SquadSeedMonitor\` (i.e.
`C:\Users\<you>\AppData\Local\SquadSeedMonitor\`) — it keeps
`seed_monitor_config.json` (your settings/favorites) and `seed_monitor.log`
(an audit log of every poll and action). Storing them here (rather than next to
the exe) means your favorites persist no matter where you move or run the app
from. Both are safe to delete; the app recreates config from defaults. If you
have an older build's config sitting next to the exe, it's migrated here
automatically on first launch.

## Notes

- No BattleMetrics API token needed — only public endpoints are used.
- Seeding by sitting AFK occupies a real player slot. Set your target below your
  server's cap so seeders free their slots before blocking live joiners at peak.
