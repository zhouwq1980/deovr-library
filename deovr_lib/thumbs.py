from __future__ import annotations

import hashlib
from pathlib import Path

from .config import THUMB_CACHE


def _src_key(src: Path) -> str:
    try:
        resolved = str(src.resolve())
    except OSError:
        resolved = str(src)
    return resolved


def thumb_cache_token(poster_path: str | None, movie_id: int) -> str:
    """给前端做 cache-bust；源文件或路径变化时 token 会变。"""
    if not poster_path:
        return str(movie_id)
    src = Path(poster_path)
    try:
        mt = int(src.stat().st_mtime) if src.is_file() else 0
    except OSError:
        mt = 0
    h = hashlib.sha1(_src_key(src).encode("utf-8", errors="ignore")).hexdigest()[:10]
    return f"{movie_id}-{mt}-{h}"


def ensure_thumb(poster_path: str | None, movie_id: int, max_width: int = 480) -> Path | None:
    """生成列表缩略图。源海报路径变化时强制重建，避免主页仍显示旧图。"""
    if not poster_path:
        return None
    src = Path(poster_path)
    if not src.is_file():
        return None

    THUMB_CACHE.mkdir(parents=True, exist_ok=True)
    out = THUMB_CACHE / f"{movie_id}.jpg"
    meta = THUMB_CACHE / f"{movie_id}.src"
    key = _src_key(src)

    try:
        src_mtime = src.stat().st_mtime
        meta_ok = meta.is_file() and meta.read_text(encoding="utf-8", errors="ignore").strip() == key
        if out.is_file() and meta_ok and out.stat().st_mtime >= src_mtime:
            return out
    except OSError:
        pass

    try:
        from PIL import Image

        with Image.open(src) as im:
            im = im.convert("RGB")
            w, h = im.size
            if w > max_width:
                nh = max(1, int(h * max_width / w))
                im = im.resize((max_width, nh), Image.Resampling.LANCZOS)
            im.save(out, "JPEG", quality=85, optimize=True)
        meta.write_text(key, encoding="utf-8")
        return out
    except Exception:
        # 缩略图失败时退回原图，避免列表空白
        return src
