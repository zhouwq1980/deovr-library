from __future__ import annotations

import json
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
DEFAULT_DB = DATA_DIR / "library.db"
DEFAULT_CONFIG = DATA_DIR / "config.json"
THUMB_CACHE = DATA_DIR / "thumbs"

DEFAULTS: dict[str, Any] = {
    "host": "0.0.0.0",
    "port": 8765,
    "libraries": [],
    "vr_screen_type": "dome",
    "vr_stereo_mode": "sbs",
    "flat_screen_type": "flat",
    "flat_stereo_mode": "off",
    "default_resolution": 2160,
    "page_size": 48,
    "deovr_section_limit": 200,
    "deovr_genre_tabs": 8,
    "deovr_actor_tabs": 0,
    "thumb_max_width": 480,
    # 自定义改地址：把 STRM 里的源主机改写成局域网 IP
    "rewrite_localhost_enabled": True,
    "rewrite_to": "192.168.0.18",
    # 要替换的源主机（可含旧局域网 IP，如 192.168.0.16）；回环地址会自动并入
    "rewrite_from": ["127.0.0.1", "localhost", "::1", "192.168.0.16"],
    # 可选：服务端跟随跳转到最终直链/CDN（与改地址可同时开；改地址作用于仍为本机的链接）
    "resolve_strm_redirects": False,
    "media_url_cache_ttl": 300,
    # 本地视频扩展名（另始终支持 .strm）
    "video_extensions": [
        ".mp4", ".mkv", ".avi", ".m4v", ".mov", ".wmv",
        ".ts", ".m2ts", ".webm", ".flv", ".mpg", ".mpeg",
    ],
}


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    THUMB_CACHE.mkdir(parents=True, exist_ok=True)


def load_config(path: Path | None = None) -> dict[str, Any]:
    ensure_dirs()
    cfg_path = path or DEFAULT_CONFIG
    cfg = dict(DEFAULTS)
    if cfg_path.exists():
        try:
            saved = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                cfg.update(saved)
        except Exception:
            pass
    return cfg


def save_config(cfg: dict[str, Any], path: Path | None = None) -> None:
    ensure_dirs()
    cfg_path = path or DEFAULT_CONFIG
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
