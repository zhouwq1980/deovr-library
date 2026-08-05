from __future__ import annotations

import queue
import socket
import threading
import traceback
import webbrowser
from pathlib import Path
from tkinter import (
    BOTH,
    END,
    LEFT,
    RIGHT,
    VERTICAL,
    BooleanVar,
    Canvas,
    Checkbutton,
    Entry,
    Frame,
    Label,
    Listbox,
    Scrollbar,
    StringVar,
    Tk,
    Toplevel,
    X,
    Y,
    filedialog,
    messagebox,
    ttk,
)
from typing import Any

from .config import (
    DEFAULT_CONFIG,
    DEFAULT_DB,
    load_config,
    reset_local_data,
    save_config,
)
from .players import merge_external_players
from .db import Database
from .scanner import scan_all

# 强制浅色高对比。按钮必须用 ttk+clam：macOS Aqua 会忽略 Button 的 bg，却保留白字 → 看不见
BG = "#e8ecf1"
FG = "#000000"
CARD = "#ffffff"
ACCENT = "#0a5fad"
BTN = "#d0d7e2"
MUTED = "#222222"
ENTRY_BG = "#ffffff"
BORDER = "#4b5563"
BAR = "#12304f"
BAR_FG = "#ffffff"
FONT = ("PingFang SC", 11)
FONT_B = ("PingFang SC", 12, "bold")
FONT_S = ("PingFang SC", 10)
FONT_TITLE = ("PingFang SC", 15, "bold")
FIXED_NAMES = {"mixed": "混合", "2d": "2D", "vr": "VR"}

_STYLE_READY = False


def _ensure_styles(root: Tk) -> None:
    """macOS 上唯有 clam 主题能稳定画出有底色的按钮。"""
    global _STYLE_READY
    if _STYLE_READY:
        return
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    def cfg(name: str, **kw: Any) -> None:
        style.configure(name, **kw)

    def mp(name: str, **kw: Any) -> None:
        style.map(name, **kw)

    cfg(
        "App.TButton",
        font=FONT,
        foreground="#000000",
        background=BTN,
        bordercolor=BORDER,
        lightcolor=BTN,
        darkcolor=BORDER,
        focuscolor=ACCENT,
        padding=(8, 4),
        relief="raised",
    )
    mp(
        "App.TButton",
        foreground=[("disabled", "#666666"), ("!disabled", "#000000")],
        background=[("active", "#b8c2d1"), ("pressed", "#a8b4c6"), ("disabled", "#e5e7eb")],
    )

    cfg(
        "Accent.TButton",
        font=FONT_B,
        foreground="#ffffff",
        background=ACCENT,
        bordercolor="#063a6b",
        lightcolor=ACCENT,
        darkcolor="#063a6b",
        focuscolor="#ffffff",
        padding=(8, 4),
        relief="raised",
    )
    mp(
        "Accent.TButton",
        foreground=[("disabled", "#dddddd"), ("!disabled", "#ffffff")],
        background=[("active", "#084a8a"), ("pressed", "#063a6b"), ("disabled", "#7aa3c9")],
    )

    cfg(
        "Bar.TButton",
        font=FONT,
        foreground="#ffffff",
        background="#2c4a6e",
        bordercolor="#0b1c2e",
        lightcolor="#2c4a6e",
        darkcolor="#0b1c2e",
        focuscolor="#ffffff",
        padding=(8, 5),
        relief="raised",
    )
    mp(
        "Bar.TButton",
        foreground=[("disabled", "#aab"), ("!disabled", "#ffffff")],
        background=[("active", "#3a5f8a"), ("pressed", "#1f3550"), ("disabled", "#5a6f86")],
    )

    cfg(
        "Go.TButton",
        font=FONT_B,
        foreground="#ffffff",
        background="#1f8a3a",
        bordercolor="#0f5a22",
        lightcolor="#1f8a3a",
        darkcolor="#0f5a22",
        focuscolor="#ffffff",
        padding=(10, 5),
        relief="raised",
    )
    mp(
        "Go.TButton",
        foreground=[("disabled", "#dfe"), ("!disabled", "#ffffff")],
        background=[("active", "#27a046"), ("pressed", "#176b2c"), ("disabled", "#7cbc8d")],
    )

    cfg(
        "Stop.TButton",
        font=FONT_B,
        foreground="#ffffff",
        background="#b42318",
        bordercolor="#7a160f",
        lightcolor="#b42318",
        darkcolor="#7a160f",
        focuscolor="#ffffff",
        padding=(8, 5),
        relief="raised",
    )
    mp(
        "Stop.TButton",
        foreground=[("disabled", "#ecc"), ("!disabled", "#ffffff")],
        background=[("active", "#d92d20"), ("pressed", "#912018"), ("disabled", "#d4a19c")],
    )
    _STYLE_READY = True


def _btn(parent: Any, text: str, command: Any, accent: bool = False) -> ttk.Button:
    style = "Accent.TButton" if accent else "App.TButton"
    return ttk.Button(parent, text=text, command=command, style=style)


def _bar_btn(parent: Any, text: str, command: Any, accent: bool = False) -> ttk.Button:
    style = "Go.TButton" if accent else "Bar.TButton"
    if "停止" in text:
        style = "Stop.TButton"
    return ttk.Button(parent, text=text, command=command, style=style)


def _entry(parent: Any, textvariable: StringVar, width: int = 16) -> Entry:
    return Entry(
        parent,
        textvariable=textvariable,
        width=width,
        font=FONT,
        bg=ENTRY_BG,
        fg=FG,
        insertbackground=FG,
        relief="solid",
        bd=1,
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=ACCENT,
    )


def _check(parent: Any, text: str, variable: BooleanVar) -> Checkbutton:
    return Checkbutton(
        parent,
        text=text,
        variable=variable,
        bg=CARD,
        fg=FG,
        activebackground=CARD,
        activeforeground=FG,
        selectcolor="#e5e7eb",
        highlightbackground=CARD,
        highlightthickness=0,
        font=FONT,
        anchor="w",
        justify=LEFT,
    )


def _card(parent: Any, title: str) -> Frame:
    wrap = Frame(parent, bg=BG)
    wrap.pack(fill=X, pady=(0, 8))
    Label(wrap, text=title, bg=BG, fg=FG, font=FONT_B, anchor="w").pack(fill=X, pady=(0, 2))
    body = Frame(
        wrap,
        bg=CARD,
        bd=1,
        relief="groove",
        padx=8,
        pady=6,
        highlightbackground=BORDER,
        highlightthickness=1,
    )
    body.pack(fill=X)
    return body


class LibraryGUI:
    def __init__(self) -> None:
        self.root = Tk()
        self.root.title("DeoVR Library 管理器")
        self.root.geometry("720x640")
        self.root.minsize(640, 480)
        self.root.configure(bg=BG)
        _ensure_styles(self.root)
        try:
            self.root.option_add("*Foreground", FG)
            self.root.option_add("*Background", CARD)
            self.root.option_add("*Entry.Foreground", FG)
            self.root.option_add("*Entry.Background", ENTRY_BG)
            self.root.option_add("*Label.Foreground", FG)
            self.root.option_add("*Checkbutton.Foreground", FG)
            self.root.option_add("*Listbox.Foreground", FG)
            self.root.option_add("*Listbox.Background", ENTRY_BG)
        except Exception:
            pass

        self.cfg = load_config()
        self.db = Database(DEFAULT_DB)
        self.server_thread: threading.Thread | None = None
        self.server: Any = None
        self.scanning = False
        self._lib_rows: list[dict[str, str]] = []
        self._ui_q: queue.Queue = queue.Queue()

        self.host_var = StringVar(value=str(self.cfg.get("host", "0.0.0.0")))
        self.port_var = StringVar(value=str(self.cfg.get("port", 8765)))
        self.force_var = BooleanVar(value=False)
        self.status_var = StringVar(value="就绪")
        detected = self._detect_ip()
        self._detected_ip = detected
        rewrite_to = str(
            self.cfg.get("rewrite_to") or self.cfg.get("lan_host") or detected or "192.168.0.18"
        )
        self.rewrite_enabled_var = BooleanVar(
            value=bool(self.cfg.get("rewrite_localhost_enabled", True))
        )
        self.rewrite_to_var = StringVar(value=rewrite_to)
        self.resolve_cdn_var = BooleanVar(value=bool(self.cfg.get("resolve_strm_redirects", False)))
        self.auto_resolve_var = BooleanVar(
            value=bool(self.cfg.get("auto_resolve_private_strm", True))
        )
        self.lock_projection_var = BooleanVar(
            value=bool(self.cfg.get("deovr_lock_projection", False))
        )
        self.use_play_url_var = BooleanVar(value=bool(self.cfg.get("deovr_use_play_url", True)))
        self.proxy_strm_var = BooleanVar(value=bool(self.cfg.get("proxy_strm", True)))
        self.hide_bare_strm_var = BooleanVar(
            value=bool(self.cfg.get("hide_strm_without_nfo_poster", False))
        )
        self.path_mixed_var = StringVar(value="")
        self.path_2d_var = StringVar(value="")
        self.path_vr_var = StringVar(value="")

        self._build()
        self._reload_libs()
        self._refresh_stats()
        self.root.after(50, self._drain_ui_queue)

    def _ui(self, fn: Any) -> None:
        """线程安全投递到主线程（勿在后台线程直接 root.after）。"""
        self._ui_q.put(fn)

    def _drain_ui_queue(self) -> None:
        try:
            while True:
                fn = self._ui_q.get_nowait()
                try:
                    fn()
                except Exception:
                    traceback.print_exc()
        except queue.Empty:
            pass
        self.root.after(50, self._drain_ui_queue)

    @staticmethod
    def _detect_ip() -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return ""

    def detect_rewrite_ip(self) -> None:
        ip = self._detect_ip()
        self._detected_ip = ip
        if ip:
            self.rewrite_to_var.set(ip)
            self.detect_lbl.config(text=f"当前检测: {ip}")
            self.status_var.set(f"已填入本机 IP: {ip}")
        else:
            messagebox.showwarning("提示", "未能自动检测本机局域网 IP，请手动填写")

    def _build(self) -> None:
        # ===== 底部固定：启停服务（始终可见）=====
        bar = Frame(self.root, bg=BAR, padx=10, pady=8)
        bar.pack(side="bottom", fill=X)
        row1 = Frame(bar, bg=BAR)
        row1.pack(fill=X)
        Label(row1, text="服务", bg=BAR, fg=BAR_FG, font=FONT_B).pack(side=LEFT, padx=(0, 8))
        Label(row1, text="Host", bg=BAR, fg=BAR_FG, font=FONT_S).pack(side=LEFT)
        _entry(row1, self.host_var, 10).pack(side=LEFT, padx=(3, 6))
        Label(row1, text="Port", bg=BAR, fg=BAR_FG, font=FONT_S).pack(side=LEFT)
        _entry(row1, self.port_var, 5).pack(side=LEFT, padx=(3, 8))
        self.btn_start = _bar_btn(row1, "▶ 启动", self.start_server, accent=True)
        self.btn_start.pack(side=LEFT, padx=(0, 4))
        self.btn_stop = _bar_btn(row1, "■ 停止", self.stop_server)
        self.btn_stop.pack(side=LEFT, padx=(0, 4))
        _bar_btn(row1, "网页", self.open_web).pack(side=LEFT, padx=(0, 4))
        _bar_btn(row1, "引导", self.open_guide).pack(side=LEFT, padx=(0, 4))
        _bar_btn(row1, "DeoVR", self.copy_deovr).pack(side=LEFT)

        row2 = Frame(bar, bg=BAR)
        row2.pack(fill=X, pady=(4, 0))
        self.stats_lbl = Label(row2, text="", bg=BAR, fg="#d7e3f4", font=FONT_S, anchor="w")
        self.stats_lbl.pack(side=LEFT, fill=X, expand=True)
        Label(row2, textvariable=self.status_var, bg=BAR, fg="#ffffff", font=FONT_S, anchor="e").pack(
            side=RIGHT
        )

        # ===== 可滚动主体 =====
        shell = Frame(self.root, bg=BG)
        shell.pack(fill=BOTH, expand=True)
        canvas = Canvas(shell, bg=BG, highlightthickness=0)
        vsb = Scrollbar(shell, orient=VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=RIGHT, fill=Y)
        canvas.pack(side=LEFT, fill=BOTH, expand=True)

        outer = Frame(canvas, bg=BG, padx=10, pady=8)
        win_id = canvas.create_window((0, 0), window=outer, anchor="nw")

        def _on_frame_configure(_event: object = None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event: Any) -> None:
            canvas.itemconfigure(win_id, width=event.width)

        outer.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event: Any) -> None:
            delta = getattr(event, "delta", 0)
            if delta:
                canvas.yview_scroll(int(-1 * (delta / 120)), "units")
            elif getattr(event, "num", None) == 4:
                canvas.yview_scroll(-1, "units")
            elif getattr(event, "num", None) == 5:
                canvas.yview_scroll(1, "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        canvas.bind_all("<Button-4>", _on_mousewheel)
        canvas.bind_all("<Button-5>", _on_mousewheel)

        Label(
            outer,
            text="DeoVR Library 管理器",
            bg=BG,
            fg=FG,
            font=FONT_TITLE,
        ).pack(anchor="w")
        Label(
            outer,
            text="Emby/Jellyfin → DeoVR · 底部栏启停服务",
            bg=BG,
            fg=MUTED,
            font=FONT_S,
            anchor="w",
        ).pack(fill=X, pady=(1, 8))

        fixed = _card(outer, "① 媒体目录（2D/VR 可混放）")
        row_mix = Frame(fixed, bg=CARD)
        row_mix.pack(fill=X, pady=(0, 4))
        Label(row_mix, text="混合", bg=CARD, fg=FG, font=FONT_B, width=3).pack(side=LEFT)
        _entry(row_mix, self.path_mixed_var, 36).pack(side=LEFT, padx=4, fill=X, expand=True)
        _btn(row_mix, "选择…", lambda: self._pick_fixed("mixed")).pack(side=LEFT, padx=(0, 4))
        _btn(row_mix, "清除", lambda: self._clear_fixed("mixed")).pack(side=LEFT)

        row2d = Frame(fixed, bg=CARD)
        row2d.pack(fill=X, pady=(0, 4))
        Label(row2d, text="2D", bg=CARD, fg=FG, font=FONT_B, width=3).pack(side=LEFT)
        _entry(row2d, self.path_2d_var, 36).pack(side=LEFT, padx=4, fill=X, expand=True)
        _btn(row2d, "选择…", lambda: self._pick_fixed("2d")).pack(side=LEFT, padx=(0, 4))
        _btn(row2d, "清除", lambda: self._clear_fixed("2d")).pack(side=LEFT)

        rowvr = Frame(fixed, bg=CARD)
        rowvr.pack(fill=X, pady=(0, 4))
        Label(rowvr, text="VR", bg=CARD, fg=FG, font=FONT_B, width=3).pack(side=LEFT)
        _entry(rowvr, self.path_vr_var, 36).pack(side=LEFT, padx=4, fill=X, expand=True)
        _btn(rowvr, "选择…", lambda: self._pick_fixed("vr")).pack(side=LEFT, padx=(0, 4))
        _btn(rowvr, "清除", lambda: self._clear_fixed("vr")).pack(side=LEFT)

        Label(
            fixed,
            text="推荐用「混合」；单片 2D/VR 按文件名(_180/_SBS/VR…)与 NFO 标签识别。可选分目录仅作筛选。改完请保存再强制扫描。",
            bg=CARD,
            fg=MUTED,
            font=FONT_S,
            anchor="w",
            wraplength=640,
            justify=LEFT,
        ).pack(fill=X)

        lib = _card(outer, "② 全部媒体目录")
        list_frm = Frame(lib, bg=CARD)
        list_frm.pack(fill=X)
        self.listbox = Listbox(
            list_frm,
            height=3,
            font=FONT_S,
            bg=ENTRY_BG,
            fg=FG,
            selectbackground="#9ec5f0",
            selectforeground=FG,
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightbackground=BORDER,
            activestyle="dotbox",
        )
        sb = Scrollbar(list_frm, orient=VERTICAL, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side=LEFT, fill=X, expand=True)
        sb.pack(side=RIGHT, fill=Y)

        row_lib = Frame(lib, bg=CARD)
        row_lib.pack(fill=X, pady=(6, 0))
        _btn(row_lib, "添加目录", self.add_library).pack(side=LEFT, padx=(0, 4))
        _btn(row_lib, "移除", self.remove_library).pack(side=LEFT, padx=(0, 4))
        _btn(row_lib, "保存配置", self.save, accent=True).pack(side=LEFT, padx=(0, 4))
        _btn(row_lib, "Init Reset", self.init_reset).pack(side=LEFT)

        scan = _card(outer, "③ 扫描入库")
        _check(scan, "强制全量重扫", self.force_var).pack(anchor="w")
        row_scan = Frame(scan, bg=CARD)
        row_scan.pack(fill=X, pady=4)
        _btn(row_scan, "扫描", self.start_scan, accent=True).pack(
            side=LEFT, padx=(0, 4)
        )
        _btn(row_scan, "刷新统计", self._refresh_stats).pack(side=LEFT, padx=(0, 4))
        _btn(row_scan, "Demo", self.load_demo).pack(side=LEFT)
        self.prog_lbl = Label(scan, text="进度: —", bg=CARD, fg=MUTED, font=FONT_S, anchor="w")
        self.prog_lbl.pack(fill=X)
        self.scan_log = Label(
            scan,
            text="尚未扫描",
            bg=CARD,
            fg=MUTED,
            font=FONT_S,
            anchor="w",
            wraplength=640,
            justify=LEFT,
        )
        self.scan_log.pack(fill=X, pady=(2, 0))

        rw = _card(outer, "④ 改地址（STRM → 局域网 IP）")
        _check(
            rw,
            "启用改写：127.0.0.1 / 私网 → 下面 IP",
            self.rewrite_enabled_var,
        ).pack(anchor="w")

        row_rw = Frame(rw, bg="#e8f1ff", bd=1, relief="solid", padx=6, pady=6)
        row_rw.pack(fill=X, pady=6)
        Label(row_rw, text="改写为：", bg="#e8f1ff", fg=FG, font=FONT_B).pack(side=LEFT)
        self.rewrite_entry = _entry(row_rw, self.rewrite_to_var, 14)
        self.rewrite_entry.pack(side=LEFT, padx=4)
        _btn(row_rw, "检测 IP", self.detect_rewrite_ip).pack(side=LEFT, padx=(0, 6))
        self.detect_lbl = Label(
            row_rw,
            text=f"检测: {self._detected_ip or '未知'}",
            bg="#e8f1ff",
            fg=MUTED,
            font=FONT_S,
        )
        self.detect_lbl.pack(side=LEFT)

        _check(
            rw,
            "私网 STRM 自动解析 CDN 直链（推荐）",
            self.auto_resolve_var,
        ).pack(anchor="w")
        _check(rw, "始终解析跳转", self.resolve_cdn_var).pack(anchor="w")
        _check(
            rw,
            "DeoVR 经本服务 /play 播放（推荐，避免过期直链）",
            self.use_play_url_var,
        ).pack(anchor="w")
        _check(
            rw,
            "代理 STRM 流到头显（推荐；直链仅浏览器能下时）",
            self.proxy_strm_var,
        ).pack(anchor="w")
        _check(
            rw,
            "锁定 DeoVR 立体格式 stereoMode（勾选后常无法调 2D/3D）",
            self.lock_projection_var,
        ).pack(anchor="w")
        _check(
            rw,
            "隐藏无封面且无 NFO 的 .strm（网页 / DeoVR 不显示）",
            self.hide_bare_strm_var,
        ).pack(anchor="w")
        Label(
            rw,
            text="投影按文件名/NFO 提示 screenType，不按目录分 2D/VR；stereoMode 默认留空。Flat 片 Zoom 常灰，请用 FOV 或 Grip 抓屏。",
            bg=CARD,
            fg=MUTED,
            font=FONT_S,
            anchor="w",
            wraplength=640,
            justify=LEFT,
        ).pack(fill=X, pady=(4, 0))

        players_card = _card(outer, "⑤ 外接播放器（网页详情唤起 VLC / IINA）")
        Label(
            players_card,
            text="勾选启用并填写本机 .app / 可执行文件路径；也可在网页 /settings 修改 scheme。",
            bg=CARD,
            fg=MUTED,
            font=FONT_S,
            anchor="w",
            wraplength=640,
            justify=LEFT,
        ).pack(fill=X, pady=(0, 6))
        self._player_vars: list[dict[str, Any]] = []
        for p in merge_external_players(self.cfg.get("external_players")):
            row = Frame(players_card, bg=CARD)
            row.pack(fill=X, pady=2)
            en = BooleanVar(value=bool(p.get("enabled")))
            path_v = StringVar(value=str(p.get("path") or ""))
            scheme_v = StringVar(value=str(p.get("scheme") or ""))
            _check(row, str(p.get("name") or p["id"]), en).pack(side=LEFT)
            _entry(row, path_v, 28).pack(side=LEFT, padx=4, fill=X, expand=True)

            def _pick(var: StringVar = path_v, title: str = str(p.get("name") or "")) -> None:
                path = filedialog.askdirectory(title=f"选择 {title}（如 xxx.app）")
                if not path:
                    path = filedialog.askopenfilename(
                        title=f"选择 {title} 可执行文件",
                        filetypes=[("所有文件", "*.*")],
                    )
                if path:
                    var.set(path)

            _btn(row, "…", _pick).pack(side=LEFT)
            self._player_vars.append(
                {
                    "id": p["id"],
                    "name": p.get("name") or p["id"],
                    "enabled": en,
                    "path": path_v,
                    "scheme": scheme_v,
                }
            )

    def _libs_from_list(self) -> list[dict[str, Any]]:
        return [{"name": r["name"], "kind": r["kind"], "path": r["path"]} for r in self._lib_rows]

    def _sync_fixed_vars(self) -> None:
        by_kind = {(r.get("kind") or "").lower(): r for r in self._lib_rows}
        self.path_mixed_var.set((by_kind.get("mixed") or {}).get("path") or "")
        self.path_2d_var.set((by_kind.get("2d") or {}).get("path") or "")
        self.path_vr_var.set((by_kind.get("vr") or {}).get("path") or "")

    def _set_fixed_in_rows(self, kind: str, path: str) -> None:
        kind = kind.lower()
        name = FIXED_NAMES[kind]
        self._lib_rows = [
            r
            for r in self._lib_rows
            if (r.get("kind") or "").lower() != kind and r.get("name") != name
        ]
        self._lib_rows.append({"name": name, "kind": kind, "path": path})
        order = {"mixed": 0, "2d": 1, "vr": 2}
        self._lib_rows.sort(key=lambda x: order.get((x.get("kind") or "").lower(), 9))
        self._reload_listbox_only()
        self._sync_fixed_vars()

    def _reload_listbox_only(self) -> None:
        self.listbox.delete(0, END)
        for row in self._lib_rows:
            self.listbox.insert(END, f'{row["name"]}  [{row["kind"]}]  {row["path"]}')

    def _reload_libs(self) -> None:
        self.cfg = load_config()
        self._lib_rows = []
        for lib in self.cfg.get("libraries") or []:
            path = str(lib.get("path", ""))
            if not path or path.startswith("/path/to/"):
                continue
            self._lib_rows.append(
                {
                    "name": str(lib.get("name", "")),
                    "kind": str(lib.get("kind", "2d")),
                    "path": path,
                }
            )
        self._reload_listbox_only()
        self._sync_fixed_vars()

    def _pick_fixed(self, kind: str) -> None:
        path = filedialog.askdirectory(title=f"选择固定 {FIXED_NAMES[kind]} 目录")
        if not path:
            return
        self._set_fixed_in_rows(kind, path)
        self.status_var.set(f"已设置 {FIXED_NAMES[kind]}: {path}（记得保存）")

    def _clear_fixed(self, kind: str) -> None:
        kind = kind.lower()
        name = FIXED_NAMES[kind]
        before = len(self._lib_rows)
        self._lib_rows = [
            r
            for r in self._lib_rows
            if (r.get("kind") or "").lower() != kind and r.get("name") != name
        ]
        if len(self._lib_rows) == before:
            messagebox.showinfo("提示", f"固定 {name} 目录未设置")
            return
        self._reload_listbox_only()
        self._sync_fixed_vars()
        self.status_var.set(f"已清除固定 {name}（记得保存）")

    def _refresh_stats(self) -> None:
        try:
            st = self.db.stats()
            parts = [f"影片 {st['movies']}", f"演员 {st['actors']}", f"类型 {st['genres']}"]
            for x in st.get("by_library") or []:
                parts.append(f"{x['name']}:{x['cnt']}")
            self.stats_lbl.config(text="数据库 · " + " · ".join(parts))
            self.status_var.set(f"数据库: {DEFAULT_DB}")
        except Exception as e:
            self.stats_lbl.config(text=f"统计失败: {e}")

    def add_library(self) -> None:
        path = filedialog.askdirectory(title="选择媒体根目录")
        if not path:
            return
        win = Toplevel(self.root)
        win.title("目录设置")
        win.geometry("520x200")
        win.configure(bg=CARD)
        name_var = StringVar(value=Path(path).name)
        upper = Path(path).name.upper()
        if "VR" in upper:
            default_kind = "vr"
        elif "2D" in upper or "FLAT" in upper:
            default_kind = "2d"
        else:
            default_kind = "mixed"
        kind_var = StringVar(value=default_kind)
        Label(win, text=path, bg=CARD, fg=FG, wraplength=480, font=FONT_S, anchor="w").pack(
            fill=X, padx=12, pady=10
        )
        row = Frame(win, bg=CARD)
        row.pack(fill=X, padx=12)
        Label(row, text="名称", bg=CARD, font=FONT).pack(side=LEFT)
        _entry(row, name_var, 18).pack(side=LEFT, padx=6)
        Label(row, text="类型(mixed/2d/vr)", bg=CARD, font=FONT).pack(side=LEFT)
        _entry(row, kind_var, 8).pack(side=LEFT, padx=6)

        def ok() -> None:
            kind = kind_var.get().strip().lower()
            if kind not in ("mixed", "2d", "vr"):
                kind = "mixed"
            name = name_var.get().strip() or Path(path).name
            self._lib_rows = [r for r in self._lib_rows if r.get("name") != name]
            self._lib_rows.append({"name": name, "kind": kind, "path": path})
            self._reload_listbox_only()
            self._sync_fixed_vars()
            win.destroy()

        _btn(win, "确定", ok, accent=True).pack(pady=16)

    def remove_library(self) -> None:
        sel = list(self.listbox.curselection())
        if not sel:
            messagebox.showinfo("提示", "请先在列表中选中要删除的目录")
            return
        for i in reversed(sel):
            self.listbox.delete(i)
            del self._lib_rows[i]
        self._sync_fixed_vars()

    def _apply_form_to_cfg(self) -> bool:
        # 固定槽位以输入框为准：有路径则覆盖，空则清除该 kind
        for kind, var, label in (
            ("mixed", self.path_mixed_var, "混合"),
            ("2d", self.path_2d_var, "2D"),
            ("vr", self.path_vr_var, "VR"),
        ):
            p = var.get().strip()
            if p:
                if not Path(p).expanduser().is_dir():
                    messagebox.showerror("错误", f"{label} 目录不存在:\n{p}")
                    return False
                self._set_fixed_in_rows(kind, str(Path(p).expanduser().resolve()))
            else:
                name = FIXED_NAMES[kind]
                self._lib_rows = [
                    r
                    for r in self._lib_rows
                    if (r.get("kind") or "").lower() != kind and r.get("name") != name
                ]
        self._reload_listbox_only()
        self._sync_fixed_vars()

        self.cfg["libraries"] = self._libs_from_list()
        self.cfg["host"] = self.host_var.get().strip() or "0.0.0.0"
        try:
            self.cfg["port"] = int(self.port_var.get())
        except ValueError:
            messagebox.showerror("错误", "端口必须是数字")
            return False
        self.cfg["rewrite_localhost_enabled"] = bool(self.rewrite_enabled_var.get())
        self.cfg["rewrite_to"] = self.rewrite_to_var.get().strip()
        self.cfg["resolve_strm_redirects"] = bool(self.resolve_cdn_var.get())
        self.cfg["auto_resolve_private_strm"] = bool(self.auto_resolve_var.get())
        self.cfg["deovr_use_play_url"] = bool(self.use_play_url_var.get())
        self.cfg["proxy_strm"] = bool(self.proxy_strm_var.get())
        self.cfg["deovr_lock_projection"] = bool(self.lock_projection_var.get())
        self.cfg["hide_strm_without_nfo_poster"] = bool(self.hide_bare_strm_var.get())
        if getattr(self, "_player_vars", None):
            self.cfg["external_players"] = [
                {
                    "id": pv["id"],
                    "name": pv["name"],
                    "enabled": bool(pv["enabled"].get()),
                    "path": pv["path"].get().strip(),
                    "scheme": pv["scheme"].get().strip(),
                }
                for pv in self._player_vars
            ]
        return True

    def save(self) -> None:
        if not self._apply_form_to_cfg():
            return
        save_config(self.cfg, DEFAULT_CONFIG)
        self.status_var.set(f"已保存 → {DEFAULT_CONFIG}")
        messagebox.showinfo("保存", "配置已保存")

    def save_silent(self) -> bool:
        if not self._apply_form_to_cfg():
            return False
        save_config(self.cfg, DEFAULT_CONFIG)
        return True

    def init_reset(self) -> None:
        """等同 CLI `init --reset`：清除配置 / 数据库 / 封面缓存。"""
        if not messagebox.askyesno(
            "Init Reset",
            "将清空本机旧数据并重建空环境：\n"
            "· data/config.json\n"
            "· data/library.db（及 wal/shm）\n"
            "· data/thumbs/*\n\n"
            "目录里的影片文件不会删除。\n确定继续？",
        ):
            return
        if self.server is not None:
            try:
                self.server.should_exit = True
            except Exception:
                pass
            self.server = None
            try:
                self.btn_start.config(state="normal")
                self.btn_stop.config(state="disabled")
            except Exception:
                pass
        ip = self._detect_ip()
        cfg, removed = reset_local_data(rewrite_to=ip or None)
        self.cfg = cfg
        self.db = Database(DEFAULT_DB)
        self._lib_rows = []
        self.path_mixed_var.set("")
        self.path_2d_var.set("")
        self.path_vr_var.set("")
        self.force_var.set(False)
        self.rewrite_to_var.set(str(cfg.get("rewrite_to") or ""))
        self.rewrite_enabled_var.set(bool(cfg.get("rewrite_localhost_enabled", True)))
        self.resolve_cdn_var.set(bool(cfg.get("resolve_strm_redirects", False)))
        self.auto_resolve_var.set(bool(cfg.get("auto_resolve_private_strm", True)))
        self.lock_projection_var.set(bool(cfg.get("deovr_lock_projection", False)))
        self.use_play_url_var.set(bool(cfg.get("deovr_use_play_url", True)))
        self.proxy_strm_var.set(bool(cfg.get("proxy_strm", True)))
        self.hide_bare_strm_var.set(bool(cfg.get("hide_strm_without_nfo_poster", False)))
        self.host_var.set(str(cfg.get("host", "0.0.0.0")))
        self.port_var.set(str(cfg.get("port", 8765)))
        self._reload_libs()
        self._refresh_stats()
        self.prog_lbl.config(text="进度: —")
        self.scan_log.config(text="已 Init Reset，请设置混合目录后扫描")
        self.status_var.set("Init Reset 完成 · 旧数据已清除")
        detail = "\n".join(f"· {x}" for x in removed) or "· （无旧文件）"
        messagebox.showinfo(
            "Init Reset 完成",
            f"已清除：\n{detail}\n\n请设置「混合」目录 → 保存 → 强制扫描。",
        )

    # 兼容旧按钮名
    reset_all = init_reset

    def load_demo(self) -> None:
        from .config import APP_DIR

        movies = APP_DIR / "testdata" / "Movies"
        vr = APP_DIR / "testdata" / "Movies-VR"
        if not movies.is_dir():
            messagebox.showerror("错误", f"找不到示例目录:\n{movies}")
            return
        self._lib_rows = []
        self._set_fixed_in_rows("2d", str(movies.resolve()))
        if vr.is_dir():
            self._set_fixed_in_rows("vr", str(vr.resolve()))
        self.force_var.set(True)
        if self.save_silent():
            self.status_var.set("已加载 testdata，开始扫描…")
            self.start_scan()

    def start_scan(self) -> None:
        if self.scanning:
            return
        if not self.save_silent():
            return
        libs = [
            x
            for x in self._libs_from_list()
            if x.get("path") and not str(x["path"]).startswith("/path/to/")
        ]
        if not libs:
            messagebox.showwarning("提示", "请先设置 2D/VR 或添加媒体目录")
            return
        self.scanning = True
        self.prog_lbl.config(text="进度: 0%（正在枚举文件…）")
        self.scan_log.config(text="开始扫描…")
        self.status_var.set("扫描中…")
        video_exts = list(self.cfg.get("video_extensions") or [])
        force = bool(self.force_var.get())
        # 拷贝列表，避免后台线程读到被改动的结构
        libs_snap = [dict(x) for x in libs]

        def progress(msg: str, cur: int, total: int) -> None:
            def ui() -> None:
                if total <= 0:
                    self.prog_lbl.config(text=f"进度: … {msg}")
                else:
                    pct = int(100 * cur / max(total, 1))
                    self.prog_lbl.config(text=f"进度: {pct}% ({cur}/{total})")
                self.scan_log.config(text=msg)
                self.status_var.set(msg)

            self._ui(ui)

        def worker() -> None:
            try:
                # 独立 Database，避免与主线程/HTTP 服务抢同一对象
                db = Database(DEFAULT_DB)
                progress("正在枚举媒体文件…", 0, 0)
                results = scan_all(
                    db,
                    libs_snap,
                    force=force,
                    video_exts=video_exts or None,
                    progress=progress,
                )
                lines = []
                for r in results:
                    if r.get("error"):
                        lines.append(f"{r['library']}: 失败 — {r['error']}")
                        continue
                    lines.append(
                        f"{r['library']}: media={r.get('total_media', r.get('total_strm', 0))} "
                        f"+{r['added']} ~{r['updated']} skip={r['skipped']} "
                        f"-{r['removed']} ({r['elapsed']}s)"
                    )
                text = "扫描完成 · " + (" | ".join(lines) if lines else "无结果")

                def done() -> None:
                    self.scanning = False
                    self.db = Database(DEFAULT_DB)
                    self.prog_lbl.config(text="进度: 100%")
                    self.scan_log.config(text=text)
                    self._refresh_stats()
                    messagebox.showinfo("完成", text)

                self._ui(done)
            except Exception:
                err = traceback.format_exc()

                def fail() -> None:
                    self.scanning = False
                    self.scan_log.config(text="扫描失败")
                    self.status_var.set("扫描失败")
                    messagebox.showerror("扫描失败", err)

                self._ui(fail)

        threading.Thread(target=worker, daemon=True, name="deovr-scan").start()

    def _lan_ip(self) -> str:
        return self.rewrite_to_var.get().strip() or self._detect_ip() or "127.0.0.1"

    def start_server(self) -> None:
        if self.server is not None:
            messagebox.showinfo("提示", "服务已在运行")
            return
        if not self.save_silent():
            return
        if self.db.movie_count() == 0:
            if not messagebox.askyesno("提示", "数据库为空，是否仍启动服务？建议先扫描。"):
                return
        host = self.host_var.get().strip() or "0.0.0.0"
        try:
            port = int(self.port_var.get())
        except ValueError:
            messagebox.showerror("错误", "端口必须是数字")
            return

        # 重新加载配置给服务端
        self.cfg = load_config()

        def worker() -> None:
            import uvicorn

            from .server import create_app

            app = create_app(Database(DEFAULT_DB), load_config())
            config = uvicorn.Config(app, host=host, port=port, log_level="info")
            self.server = uvicorn.Server(config)
            try:
                self.server.run()
            finally:
                self.server = None

        self.server_thread = threading.Thread(target=worker, daemon=True)
        self.server_thread.start()
        ip = self._lan_ip()
        rw = self.rewrite_to_var.get().strip()
        self.status_var.set(f"已启动 http://{ip}:{port}/browse · 改写→{rw or '关'}")
        try:
            self.btn_start.config(state="disabled")
            self.btn_stop.config(state="normal")
        except Exception:
            pass
        messagebox.showinfo(
            "已启动",
            f"网页: http://127.0.0.1:{port}/browse\n"
            f"局域网: http://{ip}:{port}/browse\n"
            f"DeoVR 引导: http://{ip}:{port}/open\n"
            f"DeoVR: deovr://http://{ip}:{port}/deovr\n"
            f"改写: {'开 → ' + rw if self.rewrite_enabled_var.get() else '关'}",
        )

    def stop_server(self) -> None:
        if self.server is None:
            self.status_var.set("服务未运行")
            return
        self.server.should_exit = True
        self.status_var.set("正在停止服务…")
        try:
            self.btn_start.config(state="normal")
            self.btn_stop.config(state="disabled")
        except Exception:
            pass

    def open_web(self) -> None:
        webbrowser.open(f"http://127.0.0.1:{self.port_var.get()}/browse")

    def open_guide(self) -> None:
        ip = self._lan_ip()
        webbrowser.open(f"http://{ip}:{self.port_var.get()}/open")

    def copy_deovr(self) -> None:
        url = f"deovr://http://{self._lan_ip()}:{self.port_var.get()}/deovr"
        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        self.status_var.set(f"已复制: {url}")
        messagebox.showinfo("DeoVR 地址", url)

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    LibraryGUI().run()


if __name__ == "__main__":
    main()
