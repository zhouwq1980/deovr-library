from __future__ import annotations

from pathlib import Path

from .config import THUMB_CACHE


def ensure_thumb(poster_path: str | None, movie_id: int, max_width: int = 480) -> Path | None:
    if not poster_path:
        return None
    src = Path(poster_path)
    if not src.is_file():
        return None

    out = THUMB_CACHE / f"{movie_id}.jpg"
    try:
        src_mtime = src.stat().st_mtime
        if out.is_file() and out.stat().st_mtime >= src_mtime:
            return out
    except OSError:
        pass

    try:
        from PIL import Image

        with Image.open(src) as im:
            im = im.convert("RGB")
            w, h = im.size
            if w > max_width:
                nh = int(h * max_width / w)
                im = im.resize((max_width, nh), Image.Resampling.LANCZOS)
            THUMB_CACHE.mkdir(parents=True, exist_ok=True)
            im.save(out, "JPEG", quality=82, optimize=True)
        return out
    except Exception:
        return src