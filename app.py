"""
app.py - CustomTkinter GUI for Squad Seed Monitor (v2, stage 1).

Stage 1 scope: modern tabbed shell, Monitor tab wired to the tested core logic,
seed-layer gate, direct-connect, and a non-blocking update banner.
Favorites / Settings / Log tabs, tray, graph, and notifications come in later
stages (placeholders are present so the tab structure is visible).

Run:  python app.py   (Windows; needs `pip install customtkinter requests pycaw comtypes`)
"""

import os
import sys
import threading
import webbrowser
import tkinter as tk

import customtkinter as ctk

import core


def _resource_path(rel):
    """Path to a bundled resource in both source and PyInstaller-frozen runs."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)

try:
    from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
    PYCAW_AVAILABLE = True
except Exception:
    PYCAW_AVAILABLE = False

try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

try:
    # Distinct taskbar identity so the custom window icon is used (esp. from
    # source), instead of grouping under python.exe's icon.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SquadSeedMonitor.v2")
except Exception:
    pass


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

ACCENT = "#2fa572"        # primary green — actions & positive status
ACCENT_HOVER = "#2b9768"
WARN = "#f1c40f"          # reserved: target line + genuine warnings only
DANGER = "#e74c3c"        # destructive (shutdown)
ORANGE = "#e67e22"        # revert / kill-process
MUTED = "#8a8f98"         # secondary text
TEXT = "#e6e9ee"          # primary text & section headers
SURFACE = "#1c232b"       # card surfaces (sit above the window bg)
SURFACE_2 = "#161b21"     # nested surfaces (graph)
BORDER = "#2e3843"        # card borders & divider lines
NEUTRAL_BTN = "#3d4652"   # secondary buttons
NEUTRAL_HOVER = "#48525f"
WINDOW_BG = "#12161b"     # app background — darker so cards lift off it


class SeedMonitorApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.cfg = core.load_config()
        self.log = core.setup_logger()

        self.title(f"{core.APP_TITLE}  v{core.__version__}")
        self.geometry("620x860")
        self.minsize(600, 820)
        self.configure(fg_color=WINDOW_BG)
        try:
            ico = _resource_path(os.path.join("assets", "icon.ico"))
            if os.path.exists(ico):
                self.iconbitmap(ico)
        except Exception:
            pass
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # runtime state
        self.is_running = True
        self.time_left = self.cfg["poll_seconds"]
        self.over_threshold_count = 0
        self.shutdown_pending = False
        self.backup_ini_path = None
        self.is_muted = False
        self.seed_config_applied = False
        self.prev_seeding = None      # tracks seed->live transition for auto-revert
        self.history = core.PlayerHistory(maxlen=60)  # ~last hour at 60s polls
        self.session_peak = 0         # peak player count seen this session
        self.session_start = None     # monotonic start for duration
        self.launch_monotonic = None  # set when monitoring starts, for min-uptime guard

        import time
        self.launch_monotonic = time.monotonic()
        self.session_start = time.monotonic()

        self.action_var = ctk.StringVar(value=self.cfg["action"])
        self.res_var = ctk.StringVar(value="1024x768")
        self.fps_var = ctk.StringVar(value="5")

        self._build_ui()
        self._setup_tray()
        self.log.info("========== v%s started | server=%s target=%s conf=%s seed_gate=%s ==========",
                      core.__version__, self.cfg["server_id"] or "(none)",
                      self.cfg["target_players"], self.cfg["required_confirmations"],
                      self.cfg["require_seed_layer"])

        # Non-blocking update check (never disrupts monitoring)
        if self.cfg.get("check_updates", True):
            threading.Thread(target=self._update_check_thread, daemon=True).start()

        # Startup server: last used, else first favorite
        sid, sname, sconnect = core.resolve_startup_server(self.cfg)
        if sid:
            self.cfg.update({"server_id": sid, "server_name": sname, "connect": sconnect})
            self._refresh_server_header()
            self.check_api()
        else:
            self._set_status("No server yet - use the Server tab to find one", WARN)
        self.countdown()
        # Populate the favorites dashboard shortly after the UI is up, then keep
        # it refreshing periodically.
        self.after(1500, self._favorites_autorefresh)

    # ------------------------------------------------------------------ UI --- #
    def _build_ui(self):
        # Update banner (hidden until an update is found)
        self.banner = ctk.CTkFrame(self, fg_color="#243447")
        self.banner_label = ctk.CTkLabel(self.banner, text="", text_color=WARN,
                                          font=ctk.CTkFont(size=12, weight="bold"))
        self.banner_label.pack(side="left", padx=12, pady=6)
        self.banner_btn = ctk.CTkButton(self.banner, text="Download", width=90,
                                        command=self._open_update_url)
        self.banner_btn.pack(side="right", padx=8, pady=6)
        # not packed yet -> shown only when update found

        # Compact current-server header (always visible) with a favorite star
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(pady=(10, 4))
        self.btn_fav = ctk.CTkButton(hdr, text="☆", width=36,
                                     fg_color="#3d4652", hover_color="#4a5560",
                                     font=ctk.CTkFont(size=18),
                                     command=self.toggle_favorite_current)
        self.btn_fav.pack(side="left", padx=(0, 8))
        self.lbl_server = ctk.CTkLabel(hdr, text=self._server_text(),
                                       text_color=MUTED, font=ctk.CTkFont(size=12),
                                       wraplength=520, justify="left")
        self.lbl_server.pack(side="left")
        self._update_fav_star()

        # Tabview with larger tab labels. Tab bg = window bg so SURFACE cards lift.
        self.tabs = ctk.CTkTabview(self, height=700, fg_color=WINDOW_BG,
                                   segmented_button_selected_color=ACCENT,
                                   segmented_button_selected_hover_color=ACCENT_HOVER)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=(2, 8))
        try:
            self.tabs._segmented_button.configure(font=ctk.CTkFont(size=14, weight="bold"))
        except Exception:
            pass
        self.tab_monitor = self.tabs.add("Monitor")
        self.tab_server = self.tabs.add("Server")
        self.tab_settings = self.tabs.add("Settings")
        self.tab_log = self.tabs.add("Log")

        self._build_server_tab()
        self._build_monitor_tab()
        self._build_settings_tab()
        self._build_log_tab()
        self.tabs.set("Monitor" if self.cfg.get("server_id") else "Server")

    def _build_placeholder(self, parent, text):
        ctk.CTkLabel(parent, text=text, text_color=MUTED,
                     font=ctk.CTkFont(size=13)).pack(pady=40)

    def _build_monitor_tab(self):
        p = ctk.CTkScrollableFrame(self.tab_monitor, fg_color="transparent")
        p.pack(fill="both", expand=True)

        def section(num, title):
            hdr = ctk.CTkFrame(p, fg_color="transparent")
            hdr.pack(fill="x", padx=20, pady=(14, 2))
            ctk.CTkLabel(hdr, text=num, text_color=ACCENT,
                         font=ctk.CTkFont(size=15, weight="bold")).pack(side="left", padx=(0, 8))
            ctk.CTkLabel(hdr, text=title, text_color=TEXT,
                         font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
            return hdr

        def divider():
            ctk.CTkFrame(p, height=1, fg_color=BORDER).pack(fill="x", padx=20, pady=(12, 0))

        # --- Status card (elevated surface) ---
        status = ctk.CTkFrame(p, fg_color=SURFACE, corner_radius=12,
                              border_width=1, border_color=BORDER)
        status.pack(fill="x", padx=12, pady=(12, 2))
        row = ctk.CTkFrame(status, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(12, 2))
        left = ctk.CTkFrame(row, fg_color="transparent")
        left.pack(side="left")
        self.lbl_players = ctk.CTkLabel(left, text="--", text_color=TEXT,
                                        font=ctk.CTkFont(size=48, weight="bold"))
        self.lbl_players.pack()
        ctk.CTkLabel(left, text="PLAYERS", text_color=MUTED,
                     font=ctk.CTkFont(size=10, weight="bold")).pack()
        infocol = ctk.CTkFrame(row, fg_color="transparent")
        infocol.pack(side="left", fill="x", expand=True, padx=(18, 0))
        self.lbl_status = ctk.CTkLabel(infocol, text="Status: idle", text_color=ACCENT,
                                       font=ctk.CTkFont(size=13, weight="bold"), anchor="w")
        self.lbl_status.pack(anchor="w")
        self.lbl_layer = ctk.CTkLabel(infocol, text="Layer: --", text_color=MUTED,
                                      font=ctk.CTkFont(size=12), anchor="w",
                                      wraplength=360, justify="left")
        self.lbl_layer.pack(anchor="w")
        self.lbl_timer = ctk.CTkLabel(infocol, text="Next check in -- s", text_color=MUTED,
                                      font=ctk.CTkFont(size=11), anchor="w")
        self.lbl_timer.pack(anchor="w")
        self.graph = ctk.CTkCanvas(status, height=50, highlightthickness=0, bg=SURFACE_2)
        self.graph.pack(fill="x", padx=14, pady=(6, 14))
        self.graph.bind("<Configure>", lambda e: self._draw_graph())

        # --- Step 1: set low graphics (Squad closed) ---
        h1 = section("\u2460", "Set low graphics  \u00b7  Squad CLOSED")
        ctk.CTkButton(h1, text="\u24d8 How it works", width=104, height=26,
                      fg_color=NEUTRAL_BTN, hover_color=NEUTRAL_HOVER,
                      command=self._show_seed_mode_help).pack(side="right")
        tr = ctk.CTkFrame(p, fg_color="transparent")
        tr.pack(anchor="w", padx=20, pady=(6, 0))
        ctk.CTkLabel(tr, text="Resolution", text_color=MUTED,
                     font=ctk.CTkFont(size=10)).grid(row=0, column=0, padx=4, sticky="w")
        ctk.CTkLabel(tr, text="FPS limit", text_color=MUTED,
                     font=ctk.CTkFont(size=10)).grid(row=0, column=1, padx=4, sticky="w")
        ctk.CTkOptionMenu(tr, values=["1024x768", "1280x720", "1600x900", "1920x1080"],
                          variable=self.res_var, width=104, fg_color=NEUTRAL_BTN,
                          button_color=NEUTRAL_BTN, button_hover_color=NEUTRAL_HOVER
                          ).grid(row=1, column=0, padx=4)
        ctk.CTkOptionMenu(tr, values=["5", "15", "30", "60", "120", "144"],
                          variable=self.fps_var, width=74, fg_color=NEUTRAL_BTN,
                          button_color=NEUTRAL_BTN, button_hover_color=NEUTRAL_HOVER
                          ).grid(row=1, column=1, padx=4)
        self.btn_apply = ctk.CTkButton(tr, text="Apply", width=78, fg_color=ACCENT,
                                       hover_color=ACCENT_HOVER,
                                       command=self.toggle_apply_restore)
        self.btn_apply.grid(row=1, column=2, padx=4)
        self.btn_restore = ctk.CTkButton(tr, text="Restore", width=80, fg_color=ORANGE,
                                         hover_color="#cf6f1e", state="disabled",
                                         command=self.manual_restore)
        self.btn_restore.grid(row=1, column=3, padx=4)
        divider()

        # --- Step 2: launch & join ---
        section("\u2461", "Launch & join")
        jr = ctk.CTkFrame(p, fg_color="transparent")
        jr.pack(anchor="w", padx=20, pady=(6, 0))
        ctk.CTkButton(jr, text="Launch Squad", width=150, fg_color=NEUTRAL_BTN,
                      hover_color=NEUTRAL_HOVER,
                      command=lambda: webbrowser.open(core.LAUNCH_URL)).grid(row=0, column=0, padx=5)
        ctk.CTkButton(jr, text="Connect", width=150, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self.connect_server).grid(row=0, column=1, padx=5)
        ctk.CTkLabel(p, text="With Squad closed, Connect launches & joins. If it's already open "
                             "or lands on the menu, paste the copied address into the in-game "
                             "Custom Browser.",
                     text_color=MUTED, font=ctk.CTkFont(size=10), wraplength=540,
                     justify="left").pack(anchor="w", padx=20, pady=(6, 0))
        divider()

        # --- Step 3: while seeding (Squad open) ---
        section("\u2462", "While seeding  \u00b7  Squad open")
        ctk.CTkLabel(p, text="Live changes \u2014 use these after Squad is open.",
                     text_color=MUTED, font=ctk.CTkFont(size=10)).pack(anchor="w", padx=20,
                                                                       pady=(4, 0))
        lr = ctk.CTkFrame(p, fg_color="transparent")
        lr.pack(anchor="w", padx=20, pady=(6, 0))
        self.btn_mute = ctk.CTkButton(lr, text="Mute Audio", width=150, fg_color=NEUTRAL_BTN,
                                      hover_color=NEUTRAL_HOVER, command=self.mute_squad)
        self.btn_mute.grid(row=0, column=0, padx=5, pady=2)
        ctk.CTkButton(lr, text="Minimize Squad", width=150, fg_color=NEUTRAL_BTN,
                      hover_color=NEUTRAL_HOVER,
                      command=self.minimize_squad).grid(row=0, column=1, padx=5, pady=2)
        ctk.CTkButton(lr, text="\u21ba  Undo All (unmute + restore)", fg_color=NEUTRAL_BTN,
                      hover_color=NEUTRAL_HOVER,
                      command=self.undo_all).grid(row=1, column=0, columnspan=2, padx=5,
                                                  pady=2, sticky="ew")

        # --- When seeding is done (elevated surface; border follows the action) ---
        self.act_card = ctk.CTkFrame(p, fg_color=SURFACE, corner_radius=12,
                                     border_width=2, border_color=ACCENT)
        self.act_card.pack(fill="x", padx=12, pady=(18, 10))
        ctk.CTkLabel(self.act_card, text="\u2714  WHEN SEEDING IS DONE", text_color=TEXT,
                     font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(14, 6))
        trig = ctk.CTkFrame(self.act_card, fg_color="transparent")
        trig.pack(pady=(0, 8))
        ctk.CTkLabel(trig, text="Fires when the server reaches", text_color=MUTED,
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(0, 6))
        self.spin_target = ctk.CTkEntry(trig, width=54, justify="center",
                                        fg_color=SURFACE_2, border_color=BORDER)
        self.spin_target.insert(0, str(self.cfg["target_players"]))
        self.spin_target.grid(row=0, column=1)
        self.spin_target.bind("<FocusOut>", lambda e: self.on_settings_change())
        self.spin_target.bind("<Return>", lambda e: self.on_settings_change())
        ctk.CTkLabel(trig, text="players, then:", text_color=MUTED,
                     font=ctk.CTkFont(size=12)).grid(row=0, column=2, padx=(6, 0))
        self.action_seg = ctk.CTkSegmentedButton(
            self.act_card, values=["Do Nothing", "Kill Process", "Shutdown PC"],
            variable=self.action_var, command=self.set_action,
            selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
            font=ctk.CTkFont(size=13, weight="bold"), height=40)
        self.action_seg.pack(padx=16, fill="x")
        self.lbl_action_desc = ctk.CTkLabel(self.act_card, text="", text_color=ACCENT,
                                            font=ctk.CTkFont(size=12, weight="bold"))
        self.lbl_action_desc.pack(pady=(10, 14))
        self._update_action_desc(self.action_var.get())

        self.btn_abort = ctk.CTkButton(p, text="ABORT SHUTDOWN", fg_color=DANGER,
                                       font=ctk.CTkFont(size=14, weight="bold"),
                                       command=self.abort_shutdown)
        # shown only during a pending shutdown

    # --------------------------------------------------------- server tab --- #
    def _build_server_tab(self):
        p = self.tab_server

        # --- Search box ---
        ctk.CTkLabel(p, text="Find a server", text_color=TEXT,
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=14, pady=(12, 2))
        srow = ctk.CTkFrame(p, fg_color="transparent")
        srow.pack(fill="x", padx=14)
        self.search_entry = ctk.CTkEntry(srow, placeholder_text="Search name or paste BM ID",
                                         height=34, fg_color=SURFACE_2, border_color=BORDER)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.search_entry.bind("<Return>", lambda e: self.do_search())
        ctk.CTkButton(srow, text="Search", width=80, height=34, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, command=self.do_search).pack(side="left", padx=2)
        ctk.CTkButton(srow, text="Use ID", width=70, height=34, fg_color=NEUTRAL_BTN,
                      hover_color=NEUTRAL_HOVER, command=self.use_id).pack(side="left", padx=2)

        # --- Inline results list (no popup) ---
        self.results_header = ctk.CTkLabel(p, text="", text_color=MUTED,
                                           font=ctk.CTkFont(size=11))
        self.results_header.pack(anchor="w", padx=16, pady=(8, 0))
        self.results_scroll = ctk.CTkScrollableFrame(p, height=200, fg_color=SURFACE,
                                                     border_width=1, border_color=BORDER)
        self.results_scroll.pack(fill="x", padx=12, pady=(2, 6))

        # --- Favorites dashboard (live status across all saved servers) ---
        favhdr = ctk.CTkFrame(p, fg_color="transparent")
        favhdr.pack(fill="x", padx=14, pady=(8, 0))
        ctk.CTkLabel(favhdr, text="Favorites \u00b7 live status", text_color=TEXT,
                     font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")
        ctk.CTkButton(favhdr, text="\u2b50 Save current", width=110, fg_color=NEUTRAL_BTN,
                      hover_color=NEUTRAL_HOVER,
                      command=self.save_current_favorite).pack(side="right", padx=(6, 0))
        ctk.CTkButton(favhdr, text="\u21bb Refresh", width=84, fg_color=NEUTRAL_BTN,
                      hover_color=NEUTRAL_HOVER,
                      command=self.refresh_favorite_status).pack(side="right")
        self.fav_scroll = ctk.CTkScrollableFrame(p, height=220, fg_color=SURFACE,
                                                 border_width=1, border_color=BORDER)
        self.fav_scroll.pack(fill="both", expand=True, padx=12, pady=(2, 8))
        self._refresh_favorites()

    def _show_results(self, results):
        """Populate the inline results list (replaces the old popup)."""
        for w in self.results_scroll.winfo_children():
            w.destroy()
        self.results_header.configure(text=f"{len(results)} result(s) - click Use, or \u2b50 to save")
        for r in results:
            row = ctk.CTkFrame(self.results_scroll, fg_color="#2b3640")
            row.pack(fill="x", pady=3, padx=2)
            starred = core.is_favorite(self.cfg, r["id"])
            label = f"{r['name']}   ({r['players']}/{r['max']})"
            ctk.CTkLabel(row, text=label, anchor="w", wraplength=330
                         ).pack(side="left", fill="x", expand=True, padx=8, pady=6)
            ctk.CTkButton(row, text="Use", width=50,
                          command=lambda rr=r: self._pick(rr)).pack(side="left", padx=2)
            ctk.CTkButton(row, text=("\u2b50" if starred else "\u2606"), width=36,
                          fg_color="#3d4652",
                          command=lambda rr=r: self._star_result(rr)).pack(side="left", padx=(2, 6))

    def _star_result(self, r):
        """Save a search result straight to favorites without selecting it."""
        core.add_favorite(self.cfg, r["id"], r["name"], r.get("connect", ""),
                          r.get("query_port", 0))
        core.save_config(self.cfg)
        self.log.info("starred from search: %s", r["name"])
        self._refresh_favorites()
        # re-render results so the star fills in
        if getattr(self, "_last_results", None):
            self._show_results(self._last_results)

    def _refresh_favorites(self):
        for w in self.fav_scroll.winfo_children():
            w.destroy()
        self.fav_status_labels = {}
        favs = self.cfg.get("favorites", [])
        if not favs:
            ctk.CTkLabel(self.fav_scroll,
                         text="No favorites yet.\nSearch above, then click \u2606 to save one.",
                         text_color=MUTED).pack(pady=20)
            return
        for f in favs:
            fid = f.get("id")
            row = ctk.CTkFrame(self.fav_scroll, fg_color="#2b3640")
            row.pack(fill="x", pady=3, padx=2)
            is_current = fid == self.cfg.get("server_id")
            # left column: name + a live status line
            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True, padx=8, pady=4)
            label = ("\u25b6 " if is_current else "") + f.get("name", "(unnamed)")
            ctk.CTkLabel(info, text=label, anchor="w", wraplength=300, justify="left",
                         text_color=ACCENT if is_current else None).pack(anchor="w")
            cached = getattr(self, "_fav_status", {}).get(fid)
            st_text, st_color = cached if cached else ("\u00b7 checking\u2026", MUTED)
            stlbl = ctk.CTkLabel(info, text=st_text, anchor="w",
                                 font=ctk.CTkFont(size=11), text_color=st_color)
            stlbl.pack(anchor="w")
            self.fav_status_labels[fid] = stlbl
            # right column: actions (Use, delete). Pack delete first so Use sits left of it.
            ctk.CTkButton(row, text="\u2715", width=32, fg_color=DANGER,
                          command=lambda ff=f: self.remove_favorite(ff)).pack(side="right", padx=(2, 6))
            ctk.CTkButton(row, text="Use", width=50,
                          command=lambda ff=f: self.use_favorite(ff)).pack(side="right", padx=2)

    def refresh_favorite_status(self):
        """Poll every favorite's live player count + seeding state (dashboard)."""
        favs = self.cfg.get("favorites", [])
        ids = [f.get("id") for f in favs if f.get("id")]
        if not ids:
            return
        for fid in ids:
            lbl = getattr(self, "fav_status_labels", {}).get(fid)
            if lbl:
                try:
                    lbl.configure(text="\u00b7 checking\u2026", text_color=MUTED)
                except Exception:
                    pass
        threading.Thread(target=self._poll_favorites_thread, args=(ids,), daemon=True).start()

    def _poll_favorites_thread(self, ids):
        for fid in ids:
            try:
                info = core.bm_get_server(fid)
                seeding = core.is_seed_layer(info.get("layer", ""),
                                             info.get("game_mode", ""), self.cfg)
                players, mx = info.get("players"), info.get("max")
                if isinstance(players, int):
                    if seeding:
                        text, color = f"\u00b7 {players}/{mx} \u00b7 Seeding", WARN
                    elif players == 0:
                        text, color = f"\u00b7 {players}/{mx} \u00b7 Empty", MUTED
                    else:
                        text, color = f"\u00b7 {players}/{mx} \u00b7 Live", ACCENT
                else:
                    text, color = "\u00b7 no data", MUTED
            except Exception:
                text, color = "\u00b7 offline", DANGER
            self.after(0, lambda i=fid, t=text, c=color: self._set_fav_status(i, t, c))

    def _set_fav_status(self, fid, text, color):
        cache = getattr(self, "_fav_status", None)
        if cache is None:
            cache = self._fav_status = {}
        cache[fid] = (text, color)
        lbl = getattr(self, "fav_status_labels", {}).get(fid)
        if lbl:
            try:
                lbl.configure(text=text, text_color=color)
            except Exception:
                pass

    def _favorites_autorefresh(self):
        """Periodically refresh the favorites dashboard while the app is open."""
        try:
            if self.cfg.get("favorites"):
                self.refresh_favorite_status()
        finally:
            self.after(90_000, self._favorites_autorefresh)

    def save_current_favorite(self):
        if not self.cfg.get("server_id"):
            self._set_status("Select a server first, then save it", WARN)
            return
        core.add_favorite(self.cfg, self.cfg["server_id"],
                          self.cfg.get("server_name", ""), self.cfg.get("connect", ""),
                          self.cfg.get("query_port", 0))
        core.save_config(self.cfg)
        self.log.info("saved favorite: %s", self.cfg.get("server_name"))
        self._refresh_favorites()

    def use_favorite(self, fav):
        self.cfg.update({"server_id": fav["id"], "server_name": fav.get("name", ""),
                         "connect": fav.get("connect", ""),
                         "query_port": fav.get("query_port", 0)})
        core.save_config(self.cfg)
        self.log.info("switched to favorite: %s", fav.get("name"))
        self._refresh_server_header()
        self.over_threshold_count = 0
        self.prev_seeding = None
        self._refresh_favorites()
        self.tabs.set("Monitor")
        self.check_api()

    def remove_favorite(self, fav):
        core.remove_favorite(self.cfg, fav["id"])
        core.save_config(self.cfg)
        self.log.info("removed favorite: %s", fav.get("name"))
        self._refresh_favorites()

    # ------------------------------------------------------- settings tab --- #
    def _add_tooltip(self, widget, text):
        """Lightweight hover tooltip (CustomTkinter has none built in)."""
        tip = {"win": None}
        def show(_e):
            if tip["win"] or not text:
                return
            x = widget.winfo_rootx() + 20
            y = widget.winfo_rooty() + widget.winfo_height() + 4
            tw = tk.Toplevel(widget)
            tw.wm_overrideredirect(True)
            tw.wm_geometry(f"+{x}+{y}")
            tk.Label(tw, text=text, bg="#11151a", fg="#e6e6e6", justify="left",
                     wraplength=280, font=("Segoe UI", 9), padx=8, pady=5,
                     relief="solid", borderwidth=1).pack()
            tip["win"] = tw
        def hide(_e):
            if tip["win"]:
                tip["win"].destroy(); tip["win"] = None
        widget.bind("<Enter>", show)
        widget.bind("<Leave>", hide)

    def _build_settings_tab(self):
        p = ctk.CTkScrollableFrame(self.tab_settings, fg_color="transparent")
        p.pack(fill="both", expand=True)
        self._settings_widgets = {}

        def section(title):
            ctk.CTkLabel(p, text=title, text_color=TEXT,
                         font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=10, pady=(16, 2))

        def num_field(label, key, help_text, width=60):
            row = ctk.CTkFrame(p, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=(4, 0))
            lbl = ctk.CTkLabel(row, text=label, anchor="w", text_color=TEXT)
            lbl.pack(side="left", fill="x", expand=True)
            e = ctk.CTkEntry(row, width=width, fg_color=SURFACE_2, border_color=BORDER)
            e.insert(0, str(self.cfg.get(key, "")))
            e.pack(side="right")
            self._settings_widgets[key] = ("num", e)
            ctk.CTkLabel(p, text=help_text, text_color=MUTED, anchor="w",
                         font=ctk.CTkFont(size=10), wraplength=520
                         ).pack(anchor="w", padx=14, pady=(0, 2))
            self._add_tooltip(lbl, help_text)
            self._add_tooltip(e, help_text)

        def toggle(label, key, help_text):
            var = ctk.BooleanVar(value=bool(self.cfg.get(key, False)))
            cb = ctk.CTkCheckBox(p, text=label, variable=var)
            cb.pack(anchor="w", padx=10, pady=(6, 0))
            self._settings_widgets[key] = ("bool", var)
            ctk.CTkLabel(p, text=help_text, text_color=MUTED, anchor="w",
                         font=ctk.CTkFont(size=10), wraplength=520
                         ).pack(anchor="w", padx=30, pady=(0, 2))
            self._add_tooltip(cb, help_text)

        section("Trigger")
        num_field("Target players", "target_players",
                  "Fire the action once the server is sustained at or above this count. "
                  "Keep it below your server's cap so seeders free their slots before peak.")
        num_field("Required confirmations", "required_confirmations",
                  "How many polls in a row must be over target before firing. Higher = "
                  "safer against a single noisy reading, but slower to react.")
        num_field("Poll interval (seconds)", "poll_seconds",
                  "How often to check BattleMetrics. 60s is plenty and avoids rate limits.")
        toggle("Only fire on seed layer", "require_seed_layer",
               "Only act while the server is on a SEEDING layer. When it rotates to a live "
               "layer, hold and release seeders. Strongly recommended - it's the safest signal.")

        section("Auto-revert (return game to normal)")
        toggle("Auto-revert when server goes live (map change)", "auto_revert_on_live",
               "When the map rotates off a seed layer, automatically unmute and restore your "
               "graphics so you can immediately play.")
        toggle("Auto-revert when target is reached", "auto_revert_on_target",
               "When the target count is hit, unmute and restore graphics before the chosen "
               "action runs (even for 'Do Nothing').")

        section("Safety")
        toggle("Confirm before shutdown fires", "confirm_before_shutdown",
               "Off by default (walk-away): when seeded, the PC shuts down after the grace "
               "countdown with an ABORT button. Turn this ON to instead pop a dialog that "
               "CANCELS if you don't respond - safer, but it won't shut down while you're away.")
        num_field("Min uptime before firing (minutes)", "min_uptime_minutes",
                  "Won't fire within this many minutes of launching the app - prevents an "
                  "instant shutdown if you open it when the server is already seeded.")
        num_field("Shutdown grace window (seconds)", "shutdown_grace_seconds",
                  "Countdown before the PC actually shuts down. The ABORT button and closing "
                  "the app both cancel it within this window.")

        section("Connection")
        num_field("Connect port override (blank = auto)", "connect_port_override",
                  "Connect launches Squad with +connect <ip>:<port> using the game port "
                  "from BattleMetrics. Only set this if your host uses a different join "
                  "port. Note: Steam's connect path is buggy for Squad, so the in-game "
                  "browser is the reliable fallback (the address is copied for you).",
                  width=90)

        section("App")
        toggle("Desktop notifications", "notifications",
               "Pop a Windows toast when the server seeds or a shutdown is pending. "
               "Requires the optional 'plyer' package.")
        toggle("Check for updates at startup", "check_updates",
               "Check GitHub for a newer version when the app starts. Never interrupts "
               "monitoring - just shows a banner if one exists.")
        toggle("Minimize to tray", "minimize_to_tray",
               "Off by default: the X button quits the app. Turn this on to make X hide "
               "to the system tray instead (monitoring keeps running). Requires optional "
               "'pystray' + 'Pillow'.")

        ctk.CTkButton(p, text="Save Settings", width=160, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, command=self.save_settings_tab
                      ).pack(pady=(18, 8))
        self.lbl_settings_saved = ctk.CTkLabel(p, text="", text_color=ACCENT)
        self.lbl_settings_saved.pack(pady=(0, 6))

        section("Shortcuts")
        ctk.CTkButton(p, text="Create Desktop Shortcut", width=200, fg_color=NEUTRAL_BTN,
                      hover_color=NEUTRAL_HOVER,
                      command=self.make_desktop_shortcut).pack(pady=(2, 2))
        ctk.CTkLabel(p, text="To pin to the taskbar: launch the app, then right-click its "
                             "taskbar icon → Pin to taskbar.",
                     text_color=MUTED, font=ctk.CTkFont(size=10), wraplength=520,
                     justify="left").pack(pady=(0, 8))

        ctk.CTkLabel(p, text="(With tray enabled, the X button minimizes. Use Quit to exit fully.)",
                     text_color=MUTED, font=ctk.CTkFont(size=10)).pack()
        ctk.CTkButton(p, text="Quit Application", fg_color=DANGER, width=140,
                      command=self._real_quit).pack(pady=(4, 12))

    def make_desktop_shortcut(self):
        ok, msg = core.create_desktop_shortcut(self.log)
        self.lbl_settings_saved.configure(text=msg, text_color=ACCENT if ok else WARN)
        self.log.info("desktop shortcut: %s (%s)", ok, msg)

    # ----------------------------------------------------------- log tab --- #
    def _build_log_tab(self):
        p = self.tab_log
        bar = ctk.CTkFrame(p, fg_color="transparent")
        bar.pack(fill="x", padx=8, pady=(8, 0))
        ctk.CTkButton(bar, text="Refresh", width=80, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=self._refresh_log).pack(side="left", padx=2)
        ctk.CTkButton(bar, text="Open log folder", width=120, fg_color=NEUTRAL_BTN,
                      hover_color=NEUTRAL_HOVER,
                      command=self._open_log_folder).pack(side="left", padx=2)
        self.log_box = ctk.CTkTextbox(p, font=ctk.CTkFont(family="Consolas", size=11),
                                      fg_color=SURFACE, border_width=1, border_color=BORDER)
        self.log_box.pack(fill="both", expand=True, padx=8, pady=8)
        self._refresh_log()

    def _refresh_log(self):
        path = os.path.join(core.app_dir(), core.LOG_FILENAME)
        self.log_box.delete("1.0", "end")
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()[-300:]   # last 300 lines
            self.log_box.insert("1.0", "".join(lines))
            self.log_box.see("end")
        except FileNotFoundError:
            self.log_box.insert("1.0", "(no log file yet)")
        except Exception as e:
            self.log_box.insert("1.0", f"(could not read log: {e})")

    def _open_log_folder(self):
        try:
            os.startfile(core.app_dir())   # Windows
        except Exception as e:
            self.log.warning("open folder failed: %s", e)

    def save_settings_tab(self):
        for key, (kind, widget) in self._settings_widgets.items():
            if kind == "bool":
                self.cfg[key] = bool(widget.get())
            else:  # num
                raw = widget.get().strip()
                if key == "connect_port_override":
                    self.cfg[key] = raw if raw.isdigit() else ""
                else:
                    try:
                        self.cfg[key] = int(raw)
                    except ValueError:
                        pass  # leave prior value if unparseable
        core.save_config(self.cfg)
        self.log.info("settings saved via UI (target=%s conf=%s seed_gate=%s action=%s)",
                      self.cfg["target_players"], self.cfg["required_confirmations"],
                      self.cfg["require_seed_layer"], self.cfg["action"])
        # reflect immediately on the monitor tab
        if hasattr(self, "spin_target"):
            self.spin_target.delete(0, "end"); self.spin_target.insert(0, str(self.cfg["target_players"]))
        self._draw_graph()
        self.lbl_settings_saved.configure(text="Saved \u2713")
        self.after(2000, lambda: self.lbl_settings_saved.configure(text=""))

    # ------------------------------------------------------------ helpers --- #
    def _server_text(self):
        name = self.cfg.get("server_name") or "(no server selected)"
        connect = self.cfg.get("connect") or "no connect info"
        return f"{name}\n{connect}"

    def _refresh_server_header(self):
        """Update the always-visible server label and its favorite star."""
        self.lbl_server.configure(text=self._server_text())
        self._update_fav_star()

    def _update_fav_star(self):
        """Reflect whether the current server is favorited on the header star."""
        if not hasattr(self, "btn_fav"):
            return
        sid = self.cfg.get("server_id")
        fav = bool(sid) and core.is_favorite(self.cfg, sid)
        self.btn_fav.configure(text=("★" if fav else "☆"),
                               text_color=(WARN if fav else MUTED))

    def toggle_favorite_current(self):
        """Star toggle on the header: favorite or unfavorite the current server."""
        sid = self.cfg.get("server_id")
        if not sid:
            self._set_status("No server selected - pick one on the Server tab", WARN)
            return
        if core.is_favorite(self.cfg, sid):
            core.remove_favorite(self.cfg, sid)
            self.log.info("unfavorited: %s", self.cfg.get("server_name"))
        else:
            core.add_favorite(self.cfg, sid, self.cfg.get("server_name", ""),
                              self.cfg.get("connect", ""), self.cfg.get("query_port", 0))
            self.log.info("favorited: %s", self.cfg.get("server_name"))
        core.save_config(self.cfg)
        self._update_fav_star()
        self._refresh_favorites()

    def _target_text(self):
        return f"Target:  >= {self.cfg['target_players']} players"

    def _set_status(self, text, color=ACCENT):
        self.lbl_status.configure(text=text, text_color=color)

    # ------------------------------------------------------------ update --- #
    def _update_check_thread(self):
        result = core.check_for_update()
        if result:
            self.after(0, lambda: self._show_update_banner(result))

    def _show_update_banner(self, result):
        self._update_url = result["url"]
        self.banner_label.configure(
            text=f"Update available: {result['tag']} (you have v{core.__version__})")
        self.banner.pack(fill="x", padx=14, pady=(8, 0), before=self.tabs)
        self.log.info("update available: %s", result["tag"])

    def _open_update_url(self):
        if getattr(self, "_update_url", ""):
            webbrowser.open(self._update_url)

    # -------------------------------------------------- server selection --- #
    def do_search(self):
        query = self.search_entry.get().strip()
        if not query:
            return
        if query.isdigit():          # looks like a BM ID -> direct lookup
            self._resolve_by_id(query)
            return
        self._set_status("Searching BattleMetrics...", WARN)
        threading.Thread(target=self._search_thread, args=(query,), daemon=True).start()

    def _search_thread(self, query):
        try:
            results = core.bm_search_servers(query)
        except Exception as e:
            self.log.warning("search failed: %s", e)
            self.after(0, lambda: self._set_status("Search failed (network?)", DANGER))
            return
        if not results:
            self.after(0, lambda: self._set_status("No servers matched", WARN))
            return
        self._last_results = results
        self.after(0, lambda: self._show_results(results))

    def _pick(self, r):
        self.cfg.update({"server_id": r["id"], "server_name": r["name"],
                         "connect": r["connect"], "query_port": r.get("query_port", 0)})
        core.save_config(self.cfg)
        self.log.info("server selected: %s (id=%s)", r["name"], r["id"])
        self._refresh_server_header()
        self.over_threshold_count = 0
        self.prev_seeding = None
        self._refresh_favorites()
        self.tabs.set("Monitor")
        self.check_api()

    def use_id(self):
        val = self.search_entry.get().strip()
        if val.isdigit():
            self._resolve_by_id(val)
        else:
            self._set_status("Enter a numeric BM ID in the box first", WARN)

    def _resolve_by_id(self, sid):
        self._set_status("Looking up server...", WARN)
        def worker():
            try:
                info = core.bm_get_server(sid)
            except Exception as e:
                self.log.warning("id lookup failed: %s", e)
                self.after(0, lambda: self._set_status("Lookup failed - check ID/network", DANGER))
                return
            self.cfg.update({"server_id": sid, "server_name": info["name"],
                             "connect": info["connect"],
                             "query_port": info.get("query_port", 0)})
            core.save_config(self.cfg)
            self.log.info("server set by id: %s (%s)", sid, info["name"])
            self.after(0, self._after_id_set)
        threading.Thread(target=worker, daemon=True).start()

    def _after_id_set(self):
        self._refresh_server_header()
        self.over_threshold_count = 0
        self.prev_seeding = None
        self._refresh_favorites()
        self.check_api()

    def connect_server(self):
        connect = self.cfg.get("connect")
        if not connect:
            self._set_status("No server selected - pick one on the Server tab", WARN)
            webbrowser.open(core.LAUNCH_URL)
            return
        # Always copy the address so the in-game Custom Browser fallback is one
        # paste away.
        try:
            self.clipboard_clear()
            self.clipboard_append(connect)
        except Exception:
            pass
        # The launch+connect link only joins when Squad is CLOSED (it launches
        # WITH the connect arg). If Squad is already open, that link just focuses
        # the game without joining — so there, guide the user to the browser.
        if core.game_is_running():
            self.log.info("connect: Squad already running -> guide to browser (%s)", connect)
            self._set_status(f"Squad is already open — paste {connect} into the in-game "
                             f"Custom Browser (address copied).", WARN)
        else:
            url = core.steam_connect_url(self.cfg)
            self.log.info("connect requested -> %s", url)
            webbrowser.open(url)
            self._set_status(f"Launching Squad → {connect} (copied). Wait for the main "
                             f"menu; if it doesn't auto-join, use the in-game browser.", ACCENT)
        if not self.cfg.get("connect_help_shown"):
            self._show_connect_help(connect)

    def _show_connect_help(self, connect):
        """One-time warning: direct connect may fail (Steam bug); how to fall back."""
        win = ctk.CTkToplevel(self)
        win.title("Joining the server")
        win.geometry("460x400")
        win.transient(self)
        win.grab_set()
        try:
            win.after(200, lambda: win.iconbitmap(
                _resource_path(os.path.join("assets", "icon.ico"))))
        except Exception:
            pass
        ctk.CTkLabel(win, text="How to join the server", font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=WARN, wraplength=420).pack(pady=(16, 4), padx=16)
        ctk.CTkLabel(
            win, justify="left", wraplength=420, font=ctk.CTkFont(size=12), text_color="#d8d8d8",
            text=("Steam's direct-connect is buggy for Squad, so auto-join isn't\n"
                  "guaranteed. The address is copied to your clipboard:\n\n"
                  f"     {connect}\n\n"
                  "Best case — with Squad CLOSED, click Connect: it launches and\n"
                  "joins. Wait through the loading screens; don't click during them.\n\n"
                  "If Squad is already open, or it lands on the main menu:\n"
                  "  1.  Main menu → Custom Browser\n"
                  "  2.  Paste (Ctrl+V) the address into the search / IP box\n"
                  "  3.  Select the server and Join")
        ).pack(pady=(0, 8), padx=16, anchor="w")

        dont = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(win, text="Don't show this again", variable=dont).pack(pady=(0, 8))

        def close():
            if dont.get():
                self.cfg["connect_help_shown"] = True
                core.save_config(self.cfg)
            try:
                win.grab_release(); win.destroy()
            except Exception:
                pass
        win.protocol("WM_DELETE_WINDOW", close)
        ctk.CTkButton(win, text="Got it", width=120, command=close).pack(pady=(0, 12))

    # -------------------------------------------------------- settings --- #
    def on_settings_change(self):
        try:
            self.cfg["target_players"] = max(1, min(100, int(self.spin_target.get())))
        except Exception:
            pass
        self._draw_graph()   # target line follows the new value
        core.save_config(self.cfg)

    _ACTION_DESC = {
        "Do Nothing": ("Nothing closes — settings restore so you can keep playing.", ACCENT),
        "Kill Process": ("Squad is closed automatically. Thanks for seeding!", ORANGE),
        "Shutdown PC": ("Your PC shuts down (with a confirm + abort window).", DANGER),
    }

    def _update_action_desc(self, action):
        text, color = self._ACTION_DESC.get(action, ("", ACCENT))
        if hasattr(self, "lbl_action_desc"):
            self.lbl_action_desc.configure(text=text, text_color=color)
        # the action card's border echoes the consequence (green/orange/red)
        if hasattr(self, "act_card"):
            self.act_card.configure(border_color=color)

    def set_action(self, action):
        self.cfg["action"] = action
        core.save_config(self.cfg)
        self._update_action_desc(action)
        self.log.info("config change: action -> %s", action)

    # -------------------------------------------------------- audio/ini --- #
    def _set_squad_mute(self, mute_state):
        """Set mute (1) or unmute (0) on the Squad audio session.
        Returns True if the game session was found and set."""
        if not PYCAW_AVAILABLE:
            return None
        found = False
        for s in AudioUtilities.GetAllSessions():
            vol = s._ctl.QueryInterface(ISimpleAudioVolume)
            if s.Process and s.Process.name() == core.GAME_PROCESS:
                vol.SetMute(1 if mute_state else 0, None)
                found = True
        return found

    def mute_squad(self):
        """Toggle: mutes if unmuted, unmutes if muted."""
        if not PYCAW_AVAILABLE:
            self.btn_mute.configure(text="pycaw missing")
            return
        try:
            target_mute = not self.is_muted
            found = self._set_squad_mute(target_mute)
            if not found:
                self.btn_mute.configure(text="Game not found")
                return
            self.is_muted = target_mute
            if self.is_muted:
                self.btn_mute.configure(text="Unmute Game", fg_color="#2ecc71")
                self.log.info("game muted")
            else:
                self.btn_mute.configure(text="Mute Audio", fg_color="#3d4652")
                self.log.info("game unmuted")
        except Exception as e:
            self.log.warning("audio error: %s", e)

    def minimize_squad(self):
        """Minimize the Squad window so it nearly stops rendering while seeding."""
        if not core.game_is_running():
            self._set_status("Squad isn't running — launch it first, then minimize.", WARN)
            return
        if core.minimize_game(self.log):
            self._set_status("Squad minimized — barely using your GPU now.", ACCENT)
            self.log.info("Squad window minimized")
        else:
            self._set_status("Couldn't find the Squad window to minimize.", WARN)

    def apply_seed_settings(self):
        import shutil
        from tkinter import filedialog
        try:
            # Warn if Squad is running - it will overwrite the ini on exit,
            # which is the #1 reason applied settings "don't take".
            if core.game_is_running():
                self._set_status("Squad is RUNNING - close it first, then Apply", DANGER)
                self.log.warning("apply blocked: Squad running (would be overwritten on exit)")
                self.btn_apply.configure(text="Close Squad first", fg_color=DANGER)
                return

            ini = core.find_gameusersettings()
            if not ini:
                ini = filedialog.askopenfilename(title="Find GameUserSettings.ini",
                                                 filetypes=[("INI files", "*.ini")])
                if not ini:
                    self.btn_apply.configure(text="Not found")
                    return
            if not self.backup_ini_path:
                self.backup_ini_path = ini + ".backup"
                if os.path.exists(ini):
                    shutil.copy2(ini, self.backup_ini_path)

            rx, ry = self.res_var.get().split('x')
            fps = self.fps_var.get()
            res = core.write_seed_gfx(ini, rx, ry, fps)

            if not res["wrote"]:
                # None of the expected keys were in the file - tell the user plainly
                self.log.warning("apply: no matching keys found in %s", ini)
                self._set_status("No matching settings in ini - see log", DANGER)
                self.btn_apply.configure(text="No keys found", fg_color=DANGER)
                return

            self.log.info("applied seed config to %s | keys=%s added=%s | before=%s after=%s",
                          ini, res["keys_found"], res.get("keys_added", []),
                          res["before"], res["after"])
            self.seed_config_applied = True
            self.btn_apply.configure(text="Applied ✓", fg_color="#2ecc71", state="disabled")
            self.btn_restore.configure(state="normal")
            n = len(res["keys_found"]) + len(res.get("keys_added", []))
            self._set_status(f"Applied {rx}x{ry} @ {fps}fps ({n} keys)", ACCENT)
        except Exception as e:
            self.log.warning("config error: %s", e)
            self.btn_apply.configure(text="Error")
            self._set_status(f"Apply error: {e}", DANGER)

    def toggle_apply_restore(self):
        """Apply button doubles as Restore once settings are applied."""
        if self.seed_config_applied:
            self.manual_restore()
        else:
            self.apply_seed_settings()

    def manual_restore(self):
        """User-clicked restore. Squad rewrites the ini on exit, so restoring
        while it's running is pointless (and would consume the backup). Guard it
        with a clear message. Auto-revert uses restore_settings() directly."""
        if core.game_is_running():
            self._set_status("Close Squad first — it overwrites graphics on exit. "
                             "Restore will stick once Squad is closed.", WARN)
            self.log.info("manual restore blocked: Squad running")
            return
        self.restore_settings(user_initiated=True)

    def _show_seed_mode_help(self):
        """Popup explaining what Low-Resource Seeding Mode does and the workflow."""
        win = ctk.CTkToplevel(self)
        win.title("Low-Resource Seeding Mode")
        win.geometry("480x420")
        win.transient(self)
        win.grab_set()
        try:
            win.after(200, lambda: win.iconbitmap(
                _resource_path(os.path.join("assets", "icon.ico"))))
        except Exception:
            pass
        ctk.CTkLabel(win, text="Low-Resource Seeding Mode", text_color=WARN,
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(16, 4), padx=16)
        ctk.CTkLabel(
            win, justify="left", wraplength=430, font=ctk.CTkFont(size=12), text_color="#d8d8d8",
            text=("Seeding means sitting in a near-empty server to help it fill. This\n"
                  "mode drops Squad to minimal resolution, FPS, and quality (shadows,\n"
                  "effects, textures, render scale…) so it barely uses your GPU/CPU.\n\n"
                  "Squad reads these settings when it launches and rewrites the file\n"
                  "when it closes, so the order matters:\n\n"
                  "  1.  Close Squad\n"
                  "  2.  Pick a low Resolution + FPS limit, click Apply\n"
                  "  3.  Launch Squad — now seeding at low graphics\n"
                  "  4.  Click 'Minimize Squad' — a minimized window barely renders\n\n"
                  "When seeding is done, to play normally:\n"
                  "  5.  Close Squad → click Restore → relaunch\n\n"
                  "The FPS cap + minimizing are the two biggest savers. Mute is a live\n"
                  "change: mute AFTER Squad is open. Undo All = unmute + restore.")
        ).pack(pady=(0, 10), padx=18, anchor="w")
        ctk.CTkButton(win, text="Got it", width=120, command=win.destroy).pack(pady=(0, 12))

    def restore_settings(self, user_initiated=False):
        import shutil
        if self.backup_ini_path and os.path.exists(self.backup_ini_path):
            try:
                shutil.copy2(self.backup_ini_path, self.backup_ini_path.replace('.backup', ''))
                os.remove(self.backup_ini_path)
                self.backup_ini_path = None
                self.seed_config_applied = False
                self.log.info("graphics settings restored%s",
                              " (user)" if user_initiated else "")
                # Always reset the apply/restore buttons to the un-applied state,
                # whether the restore was manual or automatic (target/live).
                self.btn_apply.configure(text="Apply", state="normal",
                                         fg_color=("#3a7ebf", "#1f538d"))
                self.btn_restore.configure(state="disabled")
                if user_initiated and self.is_muted:
                    # Also unmute on manual restore, so "get back to playing" is one action
                    if self._set_squad_mute(False):
                        self.is_muted = False
                        self.btn_mute.configure(text="Mute Audio", fg_color="#3d4652")
                        self.log.info("game unmuted (with restore)")
            except Exception as e:
                self.log.warning("restore failed: %s", e)

    def undo_all(self):
        """One click to get back to normal play: unmute + restore graphics."""
        did = []
        if self.is_muted:
            if self._set_squad_mute(False):
                self.is_muted = False
                self.btn_mute.configure(text="Mute Audio", fg_color="#3d4652")
                did.append("unmuted")
        if self.seed_config_applied:
            self.restore_settings(user_initiated=True)
            did.append("restored graphics")
        if did:
            self.log.info("undo all: %s", " + ".join(did))
            self._set_status("Restored: " + " + ".join(did), ACCENT)
        else:
            self._set_status("Nothing to undo", MUTED)

    # ---------------------------------------------------------- polling --- #
    def check_api(self):
        if not self.is_running:
            return
        sid = self.cfg.get("server_id")
        if not sid:
            self.time_left = self.cfg["poll_seconds"]
            return
        threading.Thread(target=self._poll_thread, args=(sid,), daemon=True).start()

    def _poll_thread(self, sid):
        try:
            info = core.bm_get_server(sid)
            self.after(0, lambda: self._apply_poll(info))
        except Exception as e:
            self.log.warning("API request failed: %s", e)
            self.after(0, lambda: self._set_status("Status: offline", DANGER))

    def _apply_poll(self, info):
        players = info["players"]
        layer = info["layer"]
        mode = info.get("game_mode", "")
        if info.get("connect") and info["connect"] != self.cfg.get("connect"):
            self.cfg["connect"] = info["connect"]
            self._refresh_server_header()
        # Learn the Steam query port from the poll and remember it (also on the
        # favorite) so Connect works reliably.
        qp = info.get("query_port")
        if qp and qp != self.cfg.get("query_port"):
            self.cfg["query_port"] = qp
            for f in self.cfg.get("favorites", []):
                if f.get("id") == self.cfg.get("server_id"):
                    f["query_port"] = qp
            core.save_config(self.cfg)

        # layer display
        suffix = f"  [{mode}]" if mode else ""
        seeding = core.is_seed_layer(layer, mode, self.cfg)
        self.lbl_layer.configure(
            text=f"Layer: {layer or 'unknown'}{suffix}" + ("  (seeding)" if seeding else ""),
            text_color=WARN if (self.cfg['require_seed_layer'] and seeding) else MUTED)

        if not isinstance(players, int) or players < self.cfg["min_sane_players"]:
            self.log.warning("bad player value ignored: %r", players)
            self._set_status("Status: bad data (ignored)", "#e67e22")
            self.over_threshold_count = 0
            self.time_left = self.cfg["poll_seconds"]
            return

        self.lbl_players.configure(text=str(players))
        self._set_status("Status: online", ACCENT)
        self.history.add(players)
        if players > self.session_peak:
            self.session_peak = players
        self._draw_graph()
        self.log.info("poll: players=%s layer=%s mode=%s target=%s",
                      players, layer or "unknown", mode or "?", self.cfg["target_players"])

        target = self.cfg["target_players"]
        need = self.cfg["required_confirmations"]

        if self.cfg["require_seed_layer"] and not seeding:
            # Server is on a LIVE layer. If we JUST transitioned off a seed layer,
            # auto-revert so the seeder can immediately play (unmute + restore gfx).
            if self.prev_seeding is True and self.cfg.get("auto_revert_on_live", True):
                self.log.info("server left seed layer (now '%s'); auto-reverting", layer or "unknown")
                self.auto_revert("server went live")
            if self.over_threshold_count:
                self.log.info("left seed layer (now '%s'); reset, holding", layer or "unknown")
            self.over_threshold_count = 0
            self._set_status("Live layer - reverted, ready to play", ACCENT)
        elif players >= target:
            self.over_threshold_count += 1
            self.log.info("over threshold on '%s': %s/%s", layer or "unknown",
                          self.over_threshold_count, need)
            if self.over_threshold_count >= need:
                self.trigger_action()
            else:
                self._set_status(f"Over target ({self.over_threshold_count}/{need})...", WARN)
        else:
            if self.over_threshold_count:
                self.log.info("dropped below target; reset")
            self.over_threshold_count = 0

        self.prev_seeding = seeding
        self.time_left = self.cfg["poll_seconds"]

    def auto_revert(self, reason):
        """Silently return the game to normal: unmute + restore graphics.
        Used when seeding is objectively done (server went live, or target hit),
        independent of the chosen end-action. Safe to call when nothing to revert."""
        did = []
        if self.is_muted:
            try:
                if self._set_squad_mute(False):
                    self.is_muted = False
                    self.btn_mute.configure(text="Mute Audio", fg_color="#3d4652")
                    did.append("unmuted")
            except Exception as e:
                self.log.warning("auto-unmute failed: %s", e)
        if self.seed_config_applied:
            self.restore_settings(user_initiated=True)
            did.append("restored graphics")
        if did:
            self.log.info("auto-revert (%s): %s", reason, " + ".join(did))
            if self.cfg.get("notifications", True):
                self._notify("Seeding done", f"{reason} - settings restored ({', '.join(did)})")

    def countdown(self):
        if not self.is_running:
            return
        self.lbl_timer.configure(text=f"Next check in {self.time_left} s")
        if self.time_left <= 0:
            self.check_api()
        else:
            self.time_left -= 1
        self.after(1000, self.countdown)

    # ---------------------------------------------------------- action --- #
    def _draw_graph(self):
        """Draw the recent player-count line + target line on the canvas."""
        c = self.graph
        try:
            c.delete("all")
            w = c.winfo_width() or 400
            h = c.winfo_height() or 90
            vals = self.history.values()
            target = self.cfg.get("target_players", 95)
            pad = 6
            # scale: 0..max(target, observed) with a little headroom
            top = max([target] + vals) if vals else target
            top = max(1, top) * 1.1

            def y_for(v):
                return h - pad - (v / top) * (h - 2 * pad)

            # target line
            ty = y_for(target)
            c.create_line(pad, ty, w - pad, ty, fill="#f1c40f", dash=(3, 3))
            # target label on the LEFT so it never collides with the current
            # value label (which sits at the line's right end).
            c.create_text(pad + 2, ty - 7, anchor="w", fill="#f1c40f",
                          text=f"target {target}", font=("Segoe UI", 7))

            if len(vals) < 2:
                c.create_text(w // 2, h // 2, fill="#8a8f98",
                              text="collecting data...", font=("Segoe UI", 9))
                return

            # player line
            n = len(vals)
            step = (w - 2 * pad) / (n - 1)
            pts = []
            for i, v in enumerate(vals):
                pts.append(pad + i * step)
                pts.append(y_for(v))
            c.create_line(*pts, fill="#2fa572", width=2, smooth=True)
            # last value dot + label
            lx, ly = pts[-2], pts[-1]
            c.create_oval(lx - 3, ly - 3, lx + 3, ly + 3, fill="#2fa572", outline="")
            c.create_text(lx - 6, ly - 8, anchor="e", fill="#e6e6e6",
                          text=str(vals[-1]), font=("Segoe UI", 8, "bold"))
        except Exception:
            pass  # never let a draw error disrupt anything

    def _notify(self, title, message):
        """Desktop toast (if enabled + available) plus a status-line update.
        Notification runs on a thread so it never blocks the UI."""
        try:
            self._set_status(message, ACCENT)
        except Exception:
            pass
        self.log.info("notify: %s - %s", title, message)
        if self.cfg.get("notifications", True):
            threading.Thread(
                target=lambda: core.notify(title, message, self.log),
                daemon=True).start()

    def _min_uptime_ok(self):
        import time
        mins = self.cfg.get("min_uptime_minutes", 0)
        if mins <= 0 or self.launch_monotonic is None:
            return True
        return (time.monotonic() - self.launch_monotonic) >= mins * 60

    def trigger_action(self):
        # Min-uptime guard: don't fire right after launch (stage-1 safety net)
        if not self._min_uptime_ok():
            self.log.info("threshold met but within min-uptime window; holding")
            self._set_status("Seeded, but waiting out min-uptime window...", WARN)
            return

        self.is_running = False
        self.lbl_timer.configure(text="SEED COMPLETE!", text_color=WARN)
        action = self.action_var.get()
        self.log.info("SEED COMPLETE after %s confirmations -> %s",
                      self.over_threshold_count, action)

        # Auto-revert on target hit (unmute + restore graphics), independent of the
        # end-action. Runs even for "Do Nothing" so a seeder who stays can just play.
        if self.cfg.get("auto_revert_on_target", True):
            self.auto_revert("target reached")
        else:
            self.restore_settings()  # at minimum, restore graphics

        if action == "Kill Process":
            self.log.info("executing taskkill")
            core.kill_game(self.log)
            self._set_status("Game closed. Thanks for seeding!", ACCENT)
            self._notify("Seeding complete", "Server seeded - Squad closed. Thanks!")
        elif action == "Shutdown PC":
            self._notify("Seeding complete", "Server seeded - shutdown pending")
            if self.cfg.get("confirm_before_shutdown", True):
                self._confirm_then_shutdown()
            else:
                self._execute_shutdown()
        else:
            self._set_status("Seed complete - settings restored, play on!", ACCENT)

    def _confirm_then_shutdown(self):
        """Modal dialog: user must actively confirm the shutdown. If they don't
        respond within the window, it FAILS SAFE (cancels the shutdown)."""
        win = ctk.CTkToplevel(self)
        win.title("Confirm Shutdown")
        win.geometry("380x210")
        win.transient(self)
        win.grab_set()   # modal
        win.protocol("WM_DELETE_WINDOW", lambda: self._confirm_result(win, False))

        ctk.CTkLabel(win, text="Server is seeded.", font=ctk.CTkFont(size=15, weight="bold")
                     ).pack(pady=(18, 4))
        ctk.CTkLabel(win, text="Shut down this PC?", font=ctk.CTkFont(size=13)).pack()
        self._confirm_countdown_lbl = ctk.CTkLabel(win, text="", text_color=WARN,
                                                   font=ctk.CTkFont(size=12))
        self._confirm_countdown_lbl.pack(pady=6)

        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(pady=10)
        ctk.CTkButton(btns, text="Shut Down Now", fg_color=DANGER, width=130,
                      command=lambda: self._confirm_result(win, True)).grid(row=0, column=0, padx=6)
        ctk.CTkButton(btns, text="Cancel (stay on)", fg_color=ACCENT, width=130,
                      command=lambda: self._confirm_result(win, False)).grid(row=0, column=1, padx=6)

        # auto-cancel countdown: default is SAFE (no shutdown) if ignored
        self._confirm_seconds = max(15, int(self.cfg.get("shutdown_grace_seconds", 30)))
        self._confirm_win = win
        self._confirm_tick()

    def _confirm_tick(self):
        if not getattr(self, "_confirm_win", None):
            return
        if self._confirm_seconds <= 0:
            self.log.info("shutdown confirm timed out -> defaulting to CANCEL (safe)")
            self._confirm_result(self._confirm_win, False)
            return
        self._confirm_countdown_lbl.configure(
            text=f"Auto-cancels in {self._confirm_seconds}s if no response")
        self._confirm_seconds -= 1
        self.after(1000, self._confirm_tick)

    def _confirm_result(self, win, do_shutdown):
        self._confirm_win = None
        try:
            win.grab_release(); win.destroy()
        except Exception:
            pass
        if do_shutdown:
            self.log.info("shutdown confirmed by user")
            self._execute_shutdown()
        else:
            self.log.info("shutdown declined/cancelled at confirm dialog")
            self._set_status("Shutdown cancelled - staying on.", ACCENT)
            self.lbl_timer.configure(text="Seed complete - no shutdown.", text_color=ACCENT)

    def _execute_shutdown(self):
        grace = self.cfg["shutdown_grace_seconds"]
        self.log.info("executing shutdown /s /t %s", grace)
        core.shutdown_pc(grace, self.log)
        self.shutdown_pending = True
        self.btn_abort.pack(pady=10, padx=30, fill="x")
        self._set_status(f"Shutdown in {grace}s - click ABORT to cancel", DANGER)
        self._notify("Shutdown pending", f"PC shuts down in {grace}s - ABORT to cancel")

    def abort_shutdown(self):
        if self.shutdown_pending:
            self.log.info("shutdown ABORTED by user")
            core.abort_shutdown_cmd(self.log)
            self.shutdown_pending = False
            self.btn_abort.pack_forget()
            self._set_status("Shutdown ABORTED - safe.", ACCENT)
            self.lbl_timer.configure(text="Shutdown cancelled.", text_color=ACCENT)

    # -------------------------------------------------------------- tray --- #
    def _setup_tray(self):
        """Create the system-tray icon on its own thread. Optional/graceful."""
        if not (self.cfg.get("minimize_to_tray", True) and core.tray_available()):
            self.tray_icon = None
            return
        try:
            import pystray
            from PIL import Image, ImageDraw
            # Prefer the bundled app icon; fall back to a generated green dot.
            try:
                img = Image.open(_resource_path(os.path.join("assets", "icon.ico")))
            except Exception:
                img = Image.new("RGB", (64, 64), "#1e2327")
                ImageDraw.Draw(img).ellipse((16, 16, 48, 48), fill="#2fa572")
            menu = pystray.Menu(
                pystray.MenuItem("Show", self._tray_show, default=True),
                pystray.MenuItem("Quit", self._tray_quit),
            )
            self.tray_icon = pystray.Icon("seedmon", img, core.APP_TITLE, menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
            self.log.info("system tray active")
        except Exception as e:
            self.log.warning("tray setup failed: %s", e)
            self.tray_icon = None

    def _tray_show(self, icon=None, item=None):
        # called from tray thread -> marshal to UI thread
        self.after(0, self._restore_window)

    def _restore_window(self):
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _tray_quit(self, icon=None, item=None):
        self.after(0, self._real_quit)

    def _hide_to_tray(self):
        self.withdraw()
        self.log.info("minimized to tray")
        if self.cfg.get("notifications", True):
            threading.Thread(
                target=lambda: core.notify(core.APP_TITLE,
                                           "Still running in the tray - seeding monitored",
                                           self.log),
                daemon=True).start()

    def on_closing(self):
        # If tray is active, X minimizes to tray instead of quitting.
        if getattr(self, "tray_icon", None) is not None:
            self._hide_to_tray()
            return
        self._real_quit()

    def _real_quit(self):
        if self.shutdown_pending:
            self.log.info("shutdown auto-aborted (app quit)")
            core.abort_shutdown_cmd(self.log)
        self.restore_settings()
        # Session summary for the audit trail
        try:
            import time
            dur_min = (time.monotonic() - (self.session_start or time.monotonic())) / 60
            self.log.info("session summary: duration=%.1f min | peak players=%d | "
                          "server=%s | final action=%s",
                          dur_min, self.session_peak,
                          self.cfg.get("server_name") or "(none)",
                          self.cfg.get("action"))
        except Exception:
            pass
        try:
            if getattr(self, "tray_icon", None) is not None:
                self.tray_icon.stop()
        except Exception:
            pass
        self.log.info("app quit")
        self.destroy()


if __name__ == "__main__":
    app = SeedMonitorApp()
    app.mainloop()
