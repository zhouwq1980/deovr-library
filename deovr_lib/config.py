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
    # DeoVR 投影（按单片文件名/NFO 推断，不按目录 2D/VR）：
    # false（默认）= 有线索才写 screenType，stereoMode 置空（可调 2D/3D）
    # true = 写入 screenType + stereoMode（播放器内常无法再改）
    "deovr_lock_projection": False,
    # DeoVR encodings 优先用本服务 /play/{id}（每次现解析），避免过期 CDN 直链
    "deovr_use_play_url": True,
    # /play 对 STRM 默认反向代理（带 Range），解决头显打不开仅浏览器可下的 CDN 直链
    "proxy_strm": True,
    "default_resolution": 2160,
    "page_size": 48,
    "deovr_section_limit": 200,
    "deovr_genre_tabs": 8,
    "deovr_actor_tabs": 0,
    "thumb_max_width": 480,
    # 自定义改地址：STRM 里的本机/局域网主机 → rewrite_to（公网不改）
    "rewrite_localhost_enabled": True,
    "rewrite_to": "192.168.0.18",
    # 可选：额外要改写的主机名；一般不用填，私网 IP / 127.0.0.1 会自动改
    "rewrite_from": [],
    # 显式：服务端跟随跳转到最终直链/CDN
    "resolve_strm_redirects": False,
    # 默认：STRM 指向 127.0.0.1/私网网关时自动跟随到 CDN 直链（头显才能播）
    "auto_resolve_private_strm": True,
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
