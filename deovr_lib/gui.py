from __future__ import annotations

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
    Button,
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
)
from typing import Any

from .config import DEFAULT_CONFIG, DEFAULT_DB, DEFAULTS, THUMB_CACHE, load_config, save_config
from .db import Database
from .scanner import scan_all

# 高对比，避免 macOS 白底白字 / 输入框「隐形」
BG = "#dfe3ea"
FG = "#111111"
CARD = "#f7f8fb"
ACCENT = "#0b6bcb"
BTN = "#e6ebf2"
MUTED = "#444444"
ENTRY_BG = "#ffffff"
BORDER = "#8a94a6"
FONT = ("PingFang SC", 13)
FONT_B = ("PingFang SC", 14, "bold")
FONT_S = ("PingFang SC", 12)
FIXED_NAMES = {"2d": "2D", "vr": "VR"}


def _btn(parent: Any, text: str, command: Any, accent: bool = False) -> Button:
    return Button(
        parent,
        text=text,
        command=command,
        bg=ACCENT if accent else BTN,
        fg="#ffffff" if accent else FG,
        activebackground="#09569f" if accent else "#c8d3e0",
        activeforeground="#ffffff" if accent else FG,
        relief="raised",
        bd=2,
        padx=12,
        pady=5,
        font=FONT,
        highlightthickness=0,
    )


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


def _card(parent: Any, title: str) -> Frame:
    wrap = Frame(parent, bg=BG)
    wrap.pack(fill=X, pady=(0, 12))
    Label(wrap, text=title, bg=BG, fg=FG, font=FONT_B, anchor="w").pack(fill=X, pady=(0, 4))
    body = Frame(wrap, bg=CARD, bd=2, relief="groove", padx=12, pady=10)
    body.pack(fill=X)
    return body


class LibraryGUI:
    def __init__(self) -> None:
        self.root = Tk()
        self.root.title("DeoVR Library 管理器")
        self.root.geometry("980x900")
        self.root.minsize(880, 760)
        self.root.configure(bg=BG)

        self.cfg = load_config()
        self.db = Database(DEFAULT_DB)
        self.server_thread: threading.Thread | None = None
        self.server: Any = None
        self.scanning = False
        self._lib_rows: list[dict[str, str]] = []

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
        self.path_2d_var = StringVar(value="")
        self.path_vr_var = StringVar(value="")

        self._build()
        self._reload_libs()
        self._refresh_stats()

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
        outer = Frame(self.root, bg=BG, padx=16, pady=14)
        outer.pack(fill=BOTH, expand=True)

        Label(
            outer,
            text="DeoVR Library 管理器",
            bg=BG,
            fg=FG,
            font=("PingFang SC", 20, "bold"),
        ).pack(anchor="w")
        Label(
            outer,
            text="把 Emby/Jellyfin 片库变成 DeoVR 可浏览的媒体库页",
            bg=BG,
            fg=MUTED,
            font=FONT_S,
            anchor="w",
        ).pack(fill=X, pady=(2, 12))

        # ---- 固定 2D / VR ----
        fixed = _card(outer, "① 固定 2D / VR 目录（推荐）")
        row2d = Frame(fixed, bg=CARD)
        row2d.pack(fill=X, pady=(0, 6))
        Label(row2d, text="2D", bg=CARD, fg=FG, font=FONT_B, width=4).pack(side=LEFT)
        _entry(row2d, self.path_2d_var, 52).pack(side=LEFT, padx=6, fill=X, expand=True)
        _btn(row2d, "选择…", lambda: self._pick_fixed("2d")).pack(side=LEFT, padx=(0, 6))
        _btn(row2d, "清除", lambda: self._clear_fixed("2d")).pack(side=LEFT)

        rowvr = Frame(fixed, bg=CARD)
        rowvr.pack(fill=X, pady=(0, 6))
        Label(rowvr, text="VR", bg=CARD, fg=FG, font=FONT_B, width=4).pack(side=LEFT)
        _entry(rowvr, self.path_vr_var, 52).pack(side=LEFT, padx=6, fill=X, expand=True)
        _btn(rowvr, "选择…", lambda: self._pick_fixed("vr")).pack(side=LEFT, padx=(0, 6))
        _btn(rowvr, "清除", lambda: self._clear_fixed("vr")).pack(side=LEFT)

        Label(
            fixed,
            text="再设即覆盖。改完后请点「保存配置」再扫描。",
            bg=CARD,
            fg=MUTED,
            font=FONT_S,
            anchor="w",
        ).pack(fill=X)

        # ---- 目录列表 ----
        lib = _card(outer, "② 全部媒体目录")
        list_frm = Frame(lib, bg=CARD)
        list_frm.pack(fill=X)
        self.listbox = Listbox(
            list_frm,
            height=5,
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
        row_lib.pack(fill=X, pady=(10, 0))
        _btn(row_lib, "添加其它目录", self.add_library).pack(side=LEFT, padx=(0, 8))
        _btn(row_lib, "移除选中", self.remove_library).pack(side=LEFT, padx=(0, 8))
        _btn(row_lib, "保存配置", self.save, accent=True).pack(side=LEFT, padx=(0, 8))
        _btn(row_lib, "重置全部", self.reset_all).pack(side=LEFT)

        # ---- 扫描 ----
        scan = _card(outer, "③ 扫描入库")
        Checkbutton(
            scan,
            text="强制全量重扫（忽略增量）",
            variable=self.force_var,
            bg=CARD,
            fg=FG,
            activebackground=CARD,
            selectcolor=ENTRY_BG,
            font=FONT,
            anchor="w",
        ).pack(anchor="w")
        row_scan = Frame(scan, bg=CARD)
        row_scan.pack(fill=X, pady=8)
        _btn(row_scan, "扫描并生成数据库", self.start_scan, accent=True).pack(
            side=LEFT, padx=(0, 8)
        )
        _btn(row_scan, "刷新统计", self._refresh_stats).pack(side=LEFT, padx=(0, 8))
        _btn(row_scan, "加载 Demo 示例", self.load_demo).pack(side=LEFT)
        self.prog_lbl = Label(scan, text="进度: —", bg=CARD, fg=MUTED, font=FONT_S, anchor="w")
        self.prog_lbl.pack(fill=X)
        self.scan_log = Label(
            scan,
            text="尚未扫描",
            bg=CARD,
            fg=MUTED,
            font=FONT_S,
            anchor="w",
            wraplength=900,
            justify=LEFT,
        )
        self.scan_log.pack(fill=X, pady=(4, 0))

        # ---- 改地址 ----
        rw = _card(outer, "④ 自定义改地址（STRM 本机/局域网 → 头显可访问 IP）")
        Checkbutton(
            rw,
            text="启用改写：播放时把 STRM 里的 127.0.0.1 / 私网 IP 换成下面地址",
            variable=self.rewrite_enabled_var,
            bg=CARD,
            fg=FG,
            activebackground=CARD,
            selectcolor=ENTRY_BG,
            font=FONT,
            anchor="w",
        ).pack(anchor="w")

        row_rw = Frame(rw, bg="#e8f1ff", bd=1, relief="solid", padx=10, pady=10)
        row_rw.pack(fill=X, pady=10)
        Label(row_rw, text="改写为 IP：", bg="#e8f1ff", fg=FG, font=FONT_B).pack(side=LEFT)
        self.rewrite_entry = _entry(row_rw, self.rewrite_to_var, 18)
        self.rewrite_entry.pack(side=LEFT, padx=8)
        _btn(row_rw, "检测本机 IP", self.detect_rewrite_ip).pack(side=LEFT, padx=(0, 10))
        self.detect_lbl = Label(
            row_rw,
            text=f"当前检测: {self._detected_ip or '未知'}",
            bg="#e8f1ff",
            fg=MUTED,
            font=FONT_S,
        )
        self.detect_lbl.pack(side=LEFT)

        Checkbutton(
            rw,
            text="本机/私网 STRM 自动解析到 CDN 直链（推荐，默认开）",
            variable=self.auto_resolve_var,
            bg=CARD,
            fg=FG,
            activebackground=CARD,
            selectcolor=ENTRY_BG,
            font=FONT,
            anchor="w",
        ).pack(anchor="w")
        Checkbutton(
            rw,
            text="始终解析跳转（resolve_strm_redirects）",
            variable=self.resolve_cdn_var,
            bg=CARD,
            fg=FG,
            activebackground=CARD,
            selectcolor=ENTRY_BG,
            font=FONT,
            anchor="w",
        ).pack(anchor="w")
        Label(
            rw,
            text="磁盘 .strm 不会改；详情页 /api/resolve 可看 raw → final。改完请点「保存配置」。",
            bg=CARD,
            fg=MUTED,
            font=FONT_S,
            anchor="w",
        ).pack(fill=X, pady=(6, 0))

        # ---- 服务 ----
        srv = _card(outer, "⑤ HTTP 服务")
        row_srv = Frame(srv, bg=CARD)
        row_srv.pack(fill=X)
        Label(row_srv, text="Host", bg=CARD, fg=FG, font=FONT).pack(side=LEFT)
        _entry(row_srv, self.host_var, 14).pack(side=LEFT, padx=(6, 14))
        Label(row_srv, text="Port", bg=CARD, fg=FG, font=FONT).pack(side=LEFT)
        _entry(row_srv, self.port_var, 8).pack(side=LEFT, padx=(6, 14))
        _btn(row_srv, "启动服务", self.start_server, accent=True).pack(side=LEFT, padx=(0, 8))
        _btn(row_srv, "停止服务", self.stop_server).pack(side=LEFT, padx=(0, 8))
        _btn(row_srv, "打开网页", self.open_web).pack(side=LEFT, padx=(0, 8))
        _btn(row_srv, "打开引导", self.open_guide).pack(side=LEFT, padx=(0, 8))
        _btn(row_srv, "复制 DeoVR", self.copy_deovr).pack(side=LEFT)

        self.stats_lbl = Label(outer, text="", bg=BG, fg=MUTED, font=FONT_S, anchor="w")
        self.stats_lbl.pack(fill=X, pady=(6, 0))
        Label(outer, textvariable=self.status_var, bg=BG, fg=MUTED, font=FONT_S, anchor="w").pack(
            fill=X
        )

    def _libs_from_list(self) -> list[dict[str, Any]]:
        return [{"name": r["name"], "kind": r["kind"], "path": r["path"]} for r in self._lib_rows]

    def _sync_fixed_vars(self) -> None:
        by_kind = {(r.get("kind") or "").lower(): r for r in self._lib_rows}
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
        order = {"2d": 0, "vr": 1}
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
        kind_var = StringVar(value="vr" if "VR" in Path(path).name.upper() else "2d")
        Label(win, text=path, bg=CARD, fg=FG, wraplength=480, font=FONT_S, anchor="w").pack(
            fill=X, padx=12, pady=10
        )
        row = Frame(win, bg=CARD)
        row.pack(fill=X, padx=12)
        Label(row, text="名称", bg=CARD, font=FONT).pack(side=LEFT)
        _entry(row, name_var, 18).pack(side=LEFT, padx=6)
        Label(row, text="类型(2d/vr)", bg=CARD, font=FONT).pack(side=LEFT)
        _entry(row, kind_var, 6).pack(side=LEFT, padx=6)

        def ok() -> None:
            kind = kind_var.get().strip().lower()
            if kind not in ("2d", "vr"):
                kind = "2d"
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
        p2 = self.path_2d_var.get().strip()
        pv = self.path_vr_var.get().strip()
        if p2:
            if not Path(p2).expanduser().is_dir():
                messagebox.showerror("错误", f"2D 目录不存在:\n{p2}")
                return False
            self._set_fixed_in_rows("2d", str(Path(p2).expanduser().resolve()))
        else:
            self._lib_rows = [
                r
                for r in self._lib_rows
                if (r.get("kind") or "").lower() != "2d" and r.get("name") != "2D"
            ]
        if pv:
            if not Path(pv).expanduser().is_dir():
                messagebox.showerror("错误", f"VR 目录不存在:\n{pv}")
                return False
            self._set_fixed_in_rows("vr", str(Path(pv).expanduser().resolve()))
        else:
            self._lib_rows = [
                r
                for r in self._lib_rows
                if (r.get("kind") or "").lower() != "vr" and r.get("name") != "VR"
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

    def reset_all(self) -> None:
        if not messagebox.askyesno(
            "确认重置",
            "将删除本机 config.json / library.db / thumbs，并写入空配置。\n确定？",
        ):
            return
        for p in (DEFAULT_CONFIG, DEFAULT_DB):
            try:
                if p.is_file():
                    p.unlink()
            except Exception:
                pass
        if THUMB_CACHE.is_dir():
            for f in THUMB_CACHE.glob("*"):
                try:
                    f.unlink()
                except Exception:
                    pass
        cfg = dict(DEFAULTS)
        ip = self._detect_ip()
        if ip:
            cfg["rewrite_to"] = ip
        cfg["libraries"] = []
        save_config(cfg, DEFAULT_CONFIG)
        self.cfg = cfg
        self.db = Database(DEFAULT_DB)
        self.rewrite_to_var.set(str(cfg.get("rewrite_to") or ""))
        self._reload_libs()
        self._refresh_stats()
        self.status_var.set("已重置为空配置")
        messagebox.showinfo("完成", "已重置。请重新设置 2D/VR 目录后扫描。")

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
        self.prog_lbl.config(text="进度: 0%")
        self.scan_log.config(text="开始扫描…")
        video_exts = self.cfg.get("video_extensions")

        def progress(msg: str, cur: int, total: int) -> None:
            def ui() -> None:
                pct = int(100 * cur / max(total, 1))
                self.prog_lbl.config(text=f"进度: {pct}% ({cur}/{total})")
                self.scan_log.config(text=msg)
                self.status_var.set(msg)

            self.root.after(0, ui)

        def worker() -> None:
            try:
                results = scan_all(
                    self.db,
                    libs,
                    force=self.force_var.get(),
                    video_exts=video_exts,
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
                text = "扫描完成 · " + " | ".join(lines)

                def done() -> None:
                    self.scanning = False
                    self.prog_lbl.config(text="进度: 100%")
                    self.scan_log.config(text=text)
                    self._refresh_stats()
                    messagebox.showinfo("完成", text)

                self.root.after(0, done)
            except Exception:
                err = traceback.format_exc()

                def fail() -> None:
                    self.scanning = False
                    self.scan_log.config(text="扫描失败")
                    messagebox.showerror("扫描失败", err)

                self.root.after(0, fail)

        threading.Thread(target=worker, daemon=True).start()

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
