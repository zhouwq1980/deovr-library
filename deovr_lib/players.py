"""外接播放器：URL scheme（浏览器唤起）+ 本机 path（服务端 open）。"""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import quote

# scheme 占位：{url} 原样；{url_encoded} percent-encoding
DEFAULT_EXTERNAL_PLAYERS: list[dict[str, Any]] = [
    {
        "id": "vlc",
        "name": "VLC",
        "enabled": True,
        "scheme": "vlc://{url}",
        "path": "/Applications/VLC.app",
    },
    {
        "id": "iina",
        "name": "IINA",
        "enabled": True,
        "scheme": "iina://weblink?url={url_encoded}",
        "path": "/Applications/IINA.app",
    },
    {
        "id": "mpv",
        "name": "mpv",
        "enabled": False,
        "scheme": "",
        "path": "/opt/homebrew/bin/mpv",
    },
    {
        "id": "potplayer",
        "name": "PotPlayer",
        "enabled": False,
        "scheme": "potplayer://{url}",
        "path": "",
    },
    {
        "id": "infuse",
        "name": "Infuse",
        "enabled": False,
        "scheme": "infuse://x-callback-url/play?url={url_encoded}",
        "path": "",
    },
]


def merge_external_players(saved: Any) -> list[dict[str, Any]]:
    defaults = {str(p["id"]): dict(p) for p in DEFAULT_EXTERNAL_PLAYERS}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    if isinstance(saved, list):
        for raw in saved:
            if not isinstance(raw, dict) or not raw.get("id"):
                continue
            pid = str(raw["id"]).strip()
            if not pid:
                continue
            base = dict(
                defaults.get(
                    pid,
                    {
                        "id": pid,
                        "name": pid,
                        "enabled": False,
                        "scheme": "",
                        "path": "",
                    },
                )
            )
            for key in ("name", "scheme", "path"):
                if key in raw and raw[key] is not None:
                    base[key] = str(raw[key])
            if "enabled" in raw:
                base["enabled"] = bool(raw["enabled"])
            out.append(base)
            seen.add(pid)
    for pid, base in defaults.items():
        if pid not in seen:
            out.append(dict(base))
    return out


def scheme_href(player: dict[str, Any], media_url: str) -> str:
    tmpl = (player.get("scheme") or "").strip()
    if not tmpl or not media_url:
        return ""
    return tmpl.replace("{url_encoded}", quote(media_url, safe="")).replace(
        "{url}", media_url
    )


def enabled_players(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        p
        for p in merge_external_players(cfg.get("external_players"))
        if p.get("enabled")
    ]


def players_for_movie(cfg: dict[str, Any], media_url: str) -> list[dict[str, Any]]:
    """详情页用：附带 scheme_href / has_path。"""
    rows: list[dict[str, Any]] = []
    for p in enabled_players(cfg):
        row = dict(p)
        row["scheme_href"] = scheme_href(p, media_url)
        row["has_path"] = bool((p.get("path") or "").strip())
        if row["scheme_href"] or row["has_path"]:
            rows.append(row)
    return rows


def launch_local_player(player: dict[str, Any], media_url: str) -> str:
    """在运行服务的电脑上启动播放器。返回说明字符串。"""
    path = (player.get("path") or "").strip()
    if not path:
        raise ValueError("未配置播放器路径 path")
    if not media_url:
        raise ValueError("无播放地址")

    system = platform.system()
    p = Path(path).expanduser()
    if system == "Darwin":
        app = str(p)
        if app.endswith(".app") or p.suffix == ".app":
            subprocess.Popen(
                ["open", "-na", app, "--args", media_url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return f"已在本机用 open 启动 {player.get('name') or path}"
        if not p.is_file():
            raise FileNotFoundError(f"播放器不存在: {path}")
        subprocess.Popen(
            [str(p), media_url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return f"已启动 {p.name}"
    if system == "Windows":
        if not p.exists():
            raise FileNotFoundError(f"播放器不存在: {path}")
        subprocess.Popen(
            [str(p), media_url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return f"已启动 {p.name}"
    # Linux
    if not p.is_file():
        raise FileNotFoundError(f"播放器不存在: {path}")
    subprocess.Popen(
        [str(p), media_url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return f"已启动 {p.name}"
