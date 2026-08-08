"""片种 / 地区识别：优先 NFO，不依赖 2D/VR 目录。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from .nfo import extract_code

# 经实库校验：这三类 genre 几乎 100% 真 VR
VR_GENRE_EXACT = frozenset(
    {
        "VR専用",
        "ハイクオリティVR",
        "8KVR",
        "VR",
        "Virtual Reality",
        "バーチャルリアリティ",
    }
)
_VR_GENRE_RE = re.compile(
    r"(?i)vr専用|ハイクオリティ\s*vr|8k\s*vr|^vr$|virtual\s*reality|バーチャルリアリティ"
)
_VR_TITLE_RE = re.compile(r"(?i)\[vr\]|【vr】|\(vr\)|（vr）")
# 片商名含 VR（如 KMPVR、VRBangers、SOD Create VR）
_VR_STUDIO_RE = re.compile(r"(?i)vr")
# 文件名明确投影标记（不含单独的 -360/-180 番号）
_VR_STEM_RE = re.compile(
    r"(?i)(^|[._\-\s])(180_?sbs|360_?tb|360_?sbs|180_?tb|fisheye|mkx200|mkx220|"
    r"vrca220|rf52|equirect)([._\-\s]|$)"
)


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


def detect_kind(
    *,
    genres: Iterable[Any] | None = None,
    title: str = "",
    path: str = "",
    studio: str = "",
) -> str:
    """2d | vr。优先 NFO genre，其次片商含 VR，再标题 [VR] / 文件名投影标记。"""
    for g in _genre_names(genres):
        if g in VR_GENRE_EXACT or _VR_GENRE_RE.search(g):
            return "vr"
    if studio and _VR_STUDIO_RE.search(studio):
        return "vr"
    if _VR_TITLE_RE.search(title or ""):
        return "vr"
    stem = ""
    if path:
        try:
            stem = Path(path).stem
        except Exception:
            stem = path
    if stem and _VR_STEM_RE.search(stem):
        return "vr"
    return "2d"


def detect_region(
    *,
    code: str = "",
    title: str = "",
    folder: str = "",
    path: str = "",
) -> str:
    """jp=日本（有番号）| western=欧美（无番号）。"""
    stem = ""
    if path:
        try:
            stem = Path(path).stem
        except Exception:
            stem = str(path)
    for text in (code, title, folder, stem):
        if extract_code(text or ""):
            return "jp"
    return "western"
