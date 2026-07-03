"""
core.py - non-GUI logic for Squad Seed Monitor.

Everything here is pure/testable without a display: version handling, config
load/save, BattleMetrics API access, the seed-layer gate, and the update check.
The GUI (app.py) imports from this module.
"""

import os
import re
import sys
import json
import logging
from logging.handlers import RotatingFileHandler

import requests


__version__ = "2.0.0"

# --------------------------------------------------------------------------- #
#  Constants
# --------------------------------------------------------------------------- #
APP_TITLE = "Squad Seed Monitor"
SQUAD_STEAM_APPID = "393380"
LAUNCH_URL = f"steam://run/{SQUAD_STEAM_APPID}//"
BM_API_BASE = "https://api.battlemetrics.com"
GAME_PROCESS = "SquadGame-Win64-Shipping.exe"

# Set these to your fork so the updater knows where to look.
GITHUB_OWNER = "Armyrat60"
GITHUB_REPO = "Squad-Seed-Monitor-v2"

CONFIG_FILENAME = "seed_monitor_config.json"
LOG_FILENAME = "seed_monitor.log"
LOG_MAX_BYTES = 512 * 1024
LOG_BACKUP_COUNT = 3

DEFAULT_CONFIG = {
    "favorites": [],                 # [{"id","name","connect"}]
    "server_id": "",                 # currently selected server
    "server_name": "",
    "connect": "",                   # cached "ip:port"
    "connect_port_override": "",     # blank = use BattleMetrics 'port'
    "target_players": 95,
    "required_confirmations": 3,
    "poll_seconds": 60,
    "require_seed_layer": True,
    "seed_game_modes": ["seed"],     # details.gameMode values meaning "seeding"
    "seed_layer_keywords": ["seed"], # fallback: map-name substrings
    "action": "Kill Process",        # Do Nothing | Kill Process | Shutdown PC
    "shutdown_grace_seconds": 30,
    "confirm_before_shutdown": True, # show a dialog before the first shutdown fires
    "min_uptime_minutes": 3,         # don't fire within N min of app launch
    "auto_revert_on_live": True,     # auto unmute+restore graphics when server leaves seed layer
    "auto_revert_on_target": True,   # auto unmute+restore graphics when target is hit
    "min_sane_players": 0,
    "notifications": True,           # desktop notifications
    "check_updates": True,           # check GitHub for a newer release at startup
    "minimize_to_tray": False,   # X quits the app by default; opt in to tray
}


# --------------------------------------------------------------------------- #
#  Paths / config / logging
# --------------------------------------------------------------------------- #
def app_dir():
    try:
        if getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.abspath(__file__))
        testpath = os.path.join(base, ".write_test")
        with open(testpath, "w") as f:
            f.write("")
        os.remove(testpath)
        return base
    except Exception:
        return os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))


def load_config():
    path = os.path.join(app_dir(), CONFIG_FILENAME)
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    try:
        with open(path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            for k in saved:
                if k in DEFAULT_CONFIG:
                    cfg[k] = saved[k]
    except FileNotFoundError:
        pass
    except Exception:
        pass  # corrupt -> defaults
    return _validate_config(cfg)


def _validate_config(cfg):
    """Coerce each field to the type of its default; drop junk. A corrupt or
    hand-edited config can't inject wrong-typed values into the running app."""
    for key, default in DEFAULT_CONFIG.items():
        val = cfg.get(key, default)
        try:
            if isinstance(default, bool):
                cfg[key] = bool(val)
            elif isinstance(default, int):
                cfg[key] = int(val)
            elif isinstance(default, list):
                cfg[key] = list(val) if isinstance(val, list) else default
            elif isinstance(default, str):
                cfg[key] = str(val)
            else:
                cfg[key] = val
        except (ValueError, TypeError):
            cfg[key] = default
    # favorites: keep only well-formed entries
    clean_favs = []
    for f in cfg.get("favorites", []):
        if isinstance(f, dict) and f.get("id"):
            clean_favs.append({
                "id": str(f.get("id")),
                "name": str(f.get("name", "")),
                "connect": str(f.get("connect", "")),
            })
    cfg["favorites"] = clean_favs
    return cfg


def save_config(cfg):
    path = os.path.join(app_dir(), CONFIG_FILENAME)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception:
        return False


def setup_logger():
    logger = logging.getLogger("squad_seed")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    logpath = os.path.join(app_dir(), LOG_FILENAME)
    try:
        handler = RotatingFileHandler(logpath, maxBytes=LOG_MAX_BYTES,
                                      backupCount=LOG_BACKUP_COUNT, encoding="utf-8")
    except Exception:
        import tempfile
        logpath = os.path.join(tempfile.gettempdir(), LOG_FILENAME)
        handler = RotatingFileHandler(logpath, maxBytes=LOG_MAX_BYTES,
                                      backupCount=LOG_BACKUP_COUNT, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    return logger


# --------------------------------------------------------------------------- #
#  Versioning / update check
# --------------------------------------------------------------------------- #
def parse_version(v):
    v = str(v).strip().lstrip("vV")
    parts = re.findall(r"\d+", v)
    return tuple(int(p) for p in parts[:3]) if parts else (0,)


def is_newer(latest, current):
    return parse_version(latest) > parse_version(current)


def check_for_update(timeout=6):
    """Return dict {tag, url} if a newer release exists, else None.
    Fully fail-silent: any error (offline, rate-limited, malformed) returns None
    so the update check can never disrupt monitoring."""
    if GITHUB_OWNER.startswith("YOUR_"):
        return None  # not configured yet
    try:
        url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
        resp = requests.get(url, timeout=timeout,
                            headers={"Accept": "application/vnd.github+json"})
        if resp.status_code != 200:
            return None
        data = resp.json()
        tag = data.get("tag_name", "")
        if tag and is_newer(tag, __version__):
            return {"tag": tag, "url": data.get("html_url", "")}
    except Exception:
        return None
    return None


# --------------------------------------------------------------------------- #
#  BattleMetrics API (public endpoints, no token)
# --------------------------------------------------------------------------- #
def bm_search_servers(query, limit=8):
    url = f"{BM_API_BASE}/servers"
    params = {
        "filter[game]": "squad",
        "filter[search]": query,
        "page[size]": str(limit),
        "fields[server]": "name,ip,port,players,maxPlayers,details",
    }
    resp = requests.get(url, params=params, timeout=8)
    resp.raise_for_status()
    out = []
    for item in resp.json().get("data", []):
        a = item.get("attributes", {}) or {}
        ip, port = a.get("ip"), a.get("port")
        out.append({
            "id": item.get("id"),
            "name": a.get("name", "(unnamed)"),
            "players": a.get("players"),
            "max": a.get("maxPlayers"),
            "connect": f"{ip}:{port}" if ip and port else "",
        })
    return out


def bm_get_server(server_id):
    url = f"{BM_API_BASE}/servers/{server_id}"
    resp = requests.get(url, timeout=8)
    resp.raise_for_status()
    a = resp.json().get("data", {}).get("attributes", {}) or {}
    d = a.get("details") or {}
    ip, port = a.get("ip"), a.get("port")
    return {
        "name": a.get("name", ""),
        "players": a.get("players"),
        "max": a.get("maxPlayers"),
        "layer": (d.get("map") or d.get("squad_map") or a.get("map") or ""),
        "game_mode": d.get("gameMode") or "",
        "ip": ip,
        "port": port,
        "connect": f"{ip}:{port}" if ip and port else "",
    }


# --------------------------------------------------------------------------- #
#  Seed-layer gate (pure logic)
# --------------------------------------------------------------------------- #
def is_seed_layer(layer_name, game_mode, cfg):
    """Prefer BattleMetrics gameMode ('Seed'); fall back to map-name keyword."""
    if game_mode:
        return any(m.lower() == game_mode.lower() for m in cfg["seed_game_modes"])
    if not layer_name:
        return False
    name = layer_name.lower()
    return any(kw.lower() in name for kw in cfg["seed_layer_keywords"])


def effective_connect(cfg):
    connect = cfg.get("connect") or ""
    override = str(cfg.get("connect_port_override", "")).strip()
    if connect and override.isdigit():
        ip = connect.rsplit(":", 1)[0]
        return f"{ip}:{override}"
    return connect


def steam_connect_url(connect):
    """Build the Steam URL that launches Squad AND joins a server.

    We deliberately do NOT use `steam://connect/<ip:port>`. That form asks Steam
    to query the address itself to discover which game owns it; against a Squad
    game port that query fails and Steam pops "app id specified by server is
    invalid". Instead we launch Squad explicitly by its appid and hand the game
    a `+connect` argument, so Steam never has to detect the appid.

    Returns the plain launch URL if `connect` is empty.
    """
    if not connect:
        return LAUNCH_URL
    # LAUNCH_URL already ends in the "//" that begins Squad's launch options.
    return f"{LAUNCH_URL}+connect%20{connect}"


# --------------------------------------------------------------------------- #
#  Favorites (pure list operations on cfg["favorites"])
# --------------------------------------------------------------------------- #
def add_favorite(cfg, server_id, name, connect):
    """Add or update a favorite by server_id. Returns True if added/updated."""
    if not server_id:
        return False
    favs = cfg.setdefault("favorites", [])
    for f in favs:
        if f.get("id") == server_id:
            f["name"] = name
            f["connect"] = connect
            return True
    favs.append({"id": server_id, "name": name, "connect": connect})
    return True


def remove_favorite(cfg, server_id):
    favs = cfg.get("favorites", [])
    before = len(favs)
    cfg["favorites"] = [f for f in favs if f.get("id") != server_id]
    return len(cfg["favorites"]) < before


def is_favorite(cfg, server_id):
    return any(f.get("id") == server_id for f in cfg.get("favorites", []))


def resolve_startup_server(cfg):
    """Which server to load on launch: last used if set, else first favorite.
    Returns (server_id, name, connect) or (None, "", "")."""
    if cfg.get("server_id"):
        return cfg["server_id"], cfg.get("server_name", ""), cfg.get("connect", "")
    favs = cfg.get("favorites", [])
    if favs:
        f = favs[0]
        return f.get("id", ""), f.get("name", ""), f.get("connect", "")
    return None, "", ""


# --------------------------------------------------------------------------- #
#  Desktop notifications (optional dependency, fully graceful)
# --------------------------------------------------------------------------- #
_NOTIFY_BACKEND = None  # cached: "plyer" | "none"


class PlayerHistory:
    """Fixed-size ring buffer of recent player counts for the graph.
    Keeps (timestamp, players) points, capped to maxlen."""
    def __init__(self, maxlen=60):
        from collections import deque
        self.points = deque(maxlen=maxlen)

    def add(self, players):
        import time
        if isinstance(players, int):
            self.points.append((time.time(), players))

    def values(self):
        return [p for _, p in self.points]

    def latest(self):
        return self.points[-1][1] if self.points else None

    def __len__(self):
        return len(self.points)


def notify(title, message, logger=None):
    """Show a desktop toast if possible. Never raises. Returns True if shown.
    Uses plyer if installed; silently no-ops (logging only) otherwise so a
    missing optional dependency can't break the app."""
    global _NOTIFY_BACKEND
    if _NOTIFY_BACKEND is None:
        try:
            from plyer import notification as _n   # noqa
            _NOTIFY_BACKEND = "plyer"
        except Exception:
            _NOTIFY_BACKEND = "none"
    if _NOTIFY_BACKEND == "plyer":
        try:
            from plyer import notification
            notification.notify(title=title, message=message,
                                app_name=APP_TITLE, timeout=8)
            return True
        except Exception as e:
            if logger:
                logger.warning("notification failed: %s", e)
            return False
    return False


def tray_available():
    """True if system-tray support (pystray + Pillow) is importable."""
    try:
        import pystray          # noqa
        from PIL import Image   # noqa
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- #
#  System actions (subprocess, not shell - no shell parsing/injection surface)
# --------------------------------------------------------------------------- #
def kill_game(logger=None):
    import subprocess
    try:
        subprocess.run(["taskkill", "/F", "/IM", GAME_PROCESS],
                       capture_output=True, check=False)
        return True
    except Exception as e:
        if logger:
            logger.warning("kill_game failed: %s", e)
        return False


def shutdown_pc(grace_seconds, logger=None):
    import subprocess
    try:
        subprocess.run(["shutdown", "/s", "/t", str(int(grace_seconds))],
                       capture_output=True, check=False)
        return True
    except Exception as e:
        if logger:
            logger.warning("shutdown_pc failed: %s", e)
        return False


def abort_shutdown_cmd(logger=None):
    import subprocess
    try:
        subprocess.run(["shutdown", "/a"], capture_output=True, check=False)
        return True
    except Exception as e:
        if logger:
            logger.warning("abort_shutdown failed: %s", e)
        return False


def game_is_running():
    """True if SquadGame process is currently running (best-effort)."""
    try:
        import subprocess
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {GAME_PROCESS}"],
                             capture_output=True, text=True, check=False)
        return GAME_PROCESS.lower() in (out.stdout or "").lower()
    except Exception:
        return False


# --------------------------------------------------------------------------- #
#  Graphics config (GameUserSettings.ini) - robust read/write
# --------------------------------------------------------------------------- #
def find_gameusersettings():
    """Return the first existing GameUserSettings.ini path, or None."""
    la = os.environ.get('LOCALAPPDATA', '')
    candidates = [
        os.path.join(la, 'SquadGame', 'Saved', 'Config', 'WindowsNoEditor', 'GameUserSettings.ini'),
        os.path.join(la, 'Squad', 'Saved', 'Config', 'WindowsNoEditor', 'GameUserSettings.ini'),
        os.path.join(la, 'SquadGame', 'Saved', 'Config', 'Windows', 'GameUserSettings.ini'),
    ]
    return next((p for p in candidates if os.path.exists(p)), None)


# Keys we rewrite, and how to format each value.
_RES_X_KEYS = ("ResolutionSizeX", "LastUserConfirmedResolutionSizeX", "DesiredScreenWidth")
_RES_Y_KEYS = ("ResolutionSizeY", "LastUserConfirmedResolutionSizeY", "DesiredScreenHeight")
_FPS_KEYS = ("FrameRateLimit",)


def write_seed_gfx(ini_path, res_x, res_y, fps):
    """Rewrite resolution + frame limit in the ini. Returns a dict describing
    what changed: {before:{...}, after:{...}, wrote:bool, keys_found:[...]}.
    Only touches lines that already exist (Squad's ini format)."""
    result = {"before": {}, "after": {}, "wrote": False, "keys_found": []}
    with open(ini_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    def key_of(line):
        return line.split("=", 1)[0].strip() if "=" in line else None

    out = []
    for line in lines:
        k = key_of(line)
        newline = line
        if k in _RES_X_KEYS:
            result["before"][k] = line.split("=", 1)[1].strip()
            newline = f"{k}={res_x}\n"; result["keys_found"].append(k)
        elif k in _RES_Y_KEYS:
            result["before"][k] = line.split("=", 1)[1].strip()
            newline = f"{k}={res_y}\n"; result["keys_found"].append(k)
        elif k in _FPS_KEYS:
            result["before"][k] = line.split("=", 1)[1].strip()
            newline = f"{k}={float(fps):.6f}\n"; result["keys_found"].append(k)
        if newline != line:
            result["after"][k] = newline.split("=", 1)[1].strip()
        out.append(newline)

    if result["keys_found"]:
        with open(ini_path, "w", encoding="utf-8") as f:
            f.writelines(out)
        result["wrote"] = True
    return result
