"""按文件名 / 路径 / NFO 标签推断 DeoVR 投影（不依赖目录 2D/VR 划分）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

VR_SCREENS = frozenset(
    {"dome", "sphere", "fisheye", "mkx200", "mkx220", "rf52", "fisheye190", "vrca220"}
)


@dataclass(frozen=True)
class ProjectionHint:
    screen_type: str = ""  # flat / dome / sphere / fisheye / ...
    stereo_mode: str = ""  # sbs / tb / off / cuv / ""
    kind: str = "2d"  # 2d | vr（用于网页/片库筛选，不锁定播放器）
    confidence: str = "none"  # none | soft | hard


def _norm(text: str) -> str:
    t = (text or "").lower()
    t = (
        t.replace("side-by-side", "sbs")
        .replace("side by side", "sbs")
        .replace("top-bottom", "tb")
        .replace("top bottom", "tb")
        .replace("over-under", "tb")
        .replace("over under", "tb")
        .replace("half-sbs", "sbs")
        .replace("half_sbs", "sbs")
    )
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", t)


def _genre_names(genres: Iterable[Any] | None) -> list[str]:
    out: list[str] = []
    for g in genres or []:
        if isinstance(g, dict):
            name = str(g.get("name") or "").strip()
        else:
            name = str(g).strip()
        if name:
            out.append(name)
    return out


def detect_projection(
    *,
    path: str = "",
    title: str = "",
    code: str = "",
    folder: str = "",
    genres: Iterable[Any] | None = None,
) -> ProjectionHint:
    """从单片元数据推断投影。混目录时使用，不读取 libraries.kind。"""
    names = _genre_names(genres)
    bits: list[str] = []
    if path:
        try:
            p = Path(path)
            bits.extend([p.stem, p.name, str(p.parent.name)])
        except Exception:
            bits.append(path)
    bits.extend([title or "", code or "", folder or "", *names])
    blob = _norm(" ".join(b for b in bits if b))

    screen = ""
    stereo = ""
    conf = "none"

    screen_rules: list[tuple[str, str, str]] = [
        (r"(^|_)vrca220(_|$)", "vrca220", "sbs"),
        (r"(^|_)mkx220(_|$)", "mkx220", "sbs"),
        (r"(^|_)mkx200(_|$)", "mkx200", "sbs"),
        (r"(^|_)(rf52|fisheye190)(_|$)|canon_?vr", "rf52", "cuv"),
        (r"(^|_)fisheye(_|$)", "fisheye", "sbs"),
        (r"(^|_)360(_|$)|(^|_)sphere(_|$)", "sphere", ""),
        (r"(^|_)180(_|$)|(^|_)dome(_|$)|equirect", "dome", ""),
    ]
    for pat, sc, st in screen_rules:
        if re.search(pat, blob):
            screen = sc
            if st:
                stereo = st
            conf = "hard"
            break

    if re.search(r"(^|_)(sbs|3dh|half_sbs)(_|$)|(^|_)lr(_|$)", blob):
        stereo = stereo or "sbs"
        if conf == "none":
            conf = "soft"
    if re.search(r"(^|_)(tb|3dv|overunder|over_under)(_|$)", blob):
        stereo = "tb"
        if conf == "none":
            conf = "soft"

    if not screen and re.search(r"(^|_)(flat|mono|monoscopic|2d)(_|$)", blob):
        screen = "flat"
        stereo = stereo or "off"
        if conf == "none":
            conf = "soft"

    vr_kw = bool(
        re.search(
            r"(^|_)(vr|virtual_reality|oculus|gear_?vr|psvr|quest)(_|$)|虚拟现实|全景vr|vr全景",
            blob,
        )
    ) or any(
        re.search(r"(^|[\s\[\(（])vr([\s\]\)）]|$)|虚拟现实|全景", g.lower()) for g in names
    )

    if screen in VR_SCREENS or stereo in ("sbs", "tb", "cuv"):
        kind = "vr"
        if not screen:
            screen = "dome"
        if conf == "none":
            conf = "soft"
    elif vr_kw:
        kind = "vr"
        screen = screen or "dome"
        if conf == "none":
            conf = "soft"
    elif screen == "flat":
        kind = "2d"
    else:
        # 无法从文件名/标签判断：不猜投影，交给播放器内调节
        return ProjectionHint(screen_type="", stereo_mode="", kind="2d", confidence="none")

    return ProjectionHint(
        screen_type=screen,
        stereo_mode=stereo,
        kind=kind,
        confidence=conf,
    )


def hint_from_movie(movie: dict[str, Any]) -> ProjectionHint:
    return detect_projection(
        path=str(movie.get("strm_path") or ""),
        title=str(movie.get("title") or ""),
        code=str(movie.get("code") or ""),
        folder=str(movie.get("folder_name") or ""),
        genres=movie.get("genres"),
    )
