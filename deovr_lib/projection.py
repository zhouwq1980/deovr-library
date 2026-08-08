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
    studio: str = "",
) -> ProjectionHint:
    """从单片元数据推断投影。混目录时使用，不读取 libraries.kind。"""
    from .classify import detect_kind

    names = _genre_names(genres)
    # kind 以 NFO/片商为准，避免番号里的 -360/-180 误判
    kind = detect_kind(genres=names, title=title, path=path, studio=studio)

    bits: list[str] = []
    stem = ""
    if path:
        try:
            p = Path(path)
            stem = p.stem
            bits.extend([p.stem, p.name, str(p.parent.name)])
        except Exception:
            bits.append(path)
    # 不把 code 拼进 blob，防止 SSIS-360 触发 360 投影
    bits.extend([title or "", folder or "", *names])
    blob = _norm(" ".join(b for b in bits if b))
    stem_blob = _norm(stem)

    screen = ""
    stereo = ""
    conf = "none"

    if kind == "vr":
        # NFO 已确认 VR：默认 dome+sbs，文件名可再细化 mesh
        screen = "dome"
        stereo = "sbs"
        conf = "hard"

    screen_rules: list[tuple[str, str, str]] = [
        (r"(^|_)vrca220(_|$)", "vrca220", "sbs"),
        (r"(^|_)mkx220(_|$)", "mkx220", "sbs"),
        (r"(^|_)mkx200(_|$)", "mkx200", "sbs"),
        (r"(^|_)(rf52|fisheye190)(_|$)|canon_?vr", "rf52", "cuv"),
        (r"(^|_)fisheye(_|$)", "fisheye", "sbs"),
        (r"(^|_)360_?(tb|sbs)(_|$)|(^|_)sphere(_|$)", "sphere", ""),
        (r"(^|_)180_?(sbs|tb)(_|$)|(^|_)dome(_|$)|equirect", "dome", ""),
    ]
    # 只在文件名 stem 上匹配 180/360，避免番号误伤
    for pat, sc, st in screen_rules:
        if re.search(pat, stem_blob) or (
            "360" not in pat and "180" not in pat and re.search(pat, blob)
        ):
            screen = sc
            if st:
                stereo = st
            conf = "hard"
            break

    if re.search(r"(^|_)(sbs|3dh|half_sbs)(_|$)|(^|_)lr(_|$)", stem_blob):
        stereo = stereo or "sbs"
        if conf == "none":
            conf = "soft"
    if re.search(r"(^|_)(tb|3dv|overunder|over_under)(_|$)", stem_blob):
        stereo = "tb"
        if conf == "none":
            conf = "soft"

    if kind == "2d":
        if not screen and re.search(r"(^|_)(flat|mono|monoscopic|2d)(_|$)", blob):
            screen = "flat"
            stereo = stereo or "off"
            conf = "soft" if conf == "none" else conf
        return ProjectionHint(
            screen_type=screen if screen == "flat" else "",
            stereo_mode="" if not screen else (stereo or "off"),
            kind="2d",
            confidence=conf if screen else "none",
        )

    if not screen:
        screen = "dome"
    if not stereo and screen in VR_SCREENS:
        stereo = "sbs"
    return ProjectionHint(
        screen_type=screen,
        stereo_mode=stereo or "",
        kind="vr",
        confidence=conf if conf != "none" else "soft",
    )


def hint_from_movie(movie: dict[str, Any]) -> ProjectionHint:
    return detect_projection(
        path=str(movie.get("strm_path") or ""),
        title=str(movie.get("title") or ""),
        code=str(movie.get("code") or ""),
        folder=str(movie.get("folder_name") or ""),
        genres=movie.get("genres"),
        studio=str(movie.get("studio") or ""),
    )
