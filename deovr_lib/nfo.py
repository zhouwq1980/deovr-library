from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

# 支持的媒体：STRM（远程 HTTP）+ 常见本地视频
DEFAULT_VIDEO_EXTS = (
    ".mp4",
    ".mkv",
    ".avi",
    ".m4v",
    ".mov",
    ".wmv",
    ".ts",
    ".m2ts",
    ".webm",
    ".flv",
    ".mpg",
    ".mpeg",
    ".iso",
    ".bdmv",
)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


@dataclass
class NfoMeta:
    title: str = ""
    plot: str = ""
    studio: str = ""
    year: int | None = None
    aired: str = ""
    rating: float | None = None
    runtime: int | None = None  # minutes
    actors: list[str] = field(default_factory=list)
    genres: list[str] = field(default_factory=list)
    code: str = ""
    source_file: str = ""
    root_tag: str = ""  # movie / episodedetails / episode / ...


_CODE_RE = re.compile(
    r"([A-Z]{2,10}[-_]?\d{2,5}(?:[-_]?(?:E|CD)?\d{1,2})?)",
    re.IGNORECASE,
)


def extract_code(text: str) -> str:
    if not text:
        return ""
    m = _CODE_RE.search(text.upper().replace("_", "-"))
    return m.group(1).upper() if m else ""


def _text(el: ET.Element | None) -> str:
    if el is None or el.text is None:
        return ""
    return el.text.strip()


def _first(root: ET.Element, tags: list[str]) -> str:
    for tag in tags:
        for el in root.iter(tag):
            # 只取直接有用的简单文本节点；跳过复杂容器的空文本
            t = _text(el)
            if t:
                return t
    return ""


def _rating_from_nfo(root: ET.Element) -> float | None:
    """兼容 Kodi / Emby / Jellyfin 多种评分写法。"""
    # <rating>7.4</rating>
    rating_s = _first(root, ["rating"])
    if rating_s:
        try:
            # 有时是 "7.4/10"
            rating_s = rating_s.split("/")[0].strip()
            return float(rating_s)
        except ValueError:
            pass

    # Emby/Jellyfin:
    # <ratings>
    #   <rating name="imdb" max="10" default="true"><value>7.4</value><votes>123</votes></rating>
    # </ratings>
    best: float | None = None
    for ratings in root.iter("ratings"):
        for r in ratings.findall("rating"):
            val_el = r.find("value")
            if val_el is None:
                continue
            try:
                v = float(_text(val_el))
            except ValueError:
                continue
            default = (r.attrib.get("default") or "").lower() in ("true", "1", "yes")
            if default:
                return v
            if best is None:
                best = v
    if best is not None:
        return best

    # <userrating>8</userrating>
    ur = _first(root, ["userrating"])
    if ur:
        try:
            return float(ur)
        except ValueError:
            pass
    return None


def _runtime_from_nfo(root: ET.Element) -> int | None:
    """分钟；兼容 runtime / fileinfo 秒数。"""
    runtime_s = _first(root, ["runtime"])
    if runtime_s:
        try:
            # 可能是分钟或 "142 min"
            m = re.search(r"[\d.]+", runtime_s)
            if m:
                return int(float(m.group(0)))
        except ValueError:
            pass

    # <fileinfo><streamdetails><video><durationinseconds>8520</durationinseconds>
    for el in root.iter("durationinseconds"):
        t = _text(el)
        if t.isdigit():
            return max(1, int(t) // 60)

    for el in root.iter("runtime"):
        # 有些放在 streamdetails 下仍是分钟
        t = _text(el)
        if t:
            try:
                return int(float(t))
            except ValueError:
                continue
    return None


def _unique_ids(root: ET.Element) -> dict[str, str]:
    """Emby/Jellyfin <uniqueid type="imdb">tt...</uniqueid> / type=\"num\""""
    out: dict[str, str] = {}
    for el in root.iter("uniqueid"):
        t = (el.attrib.get("type") or "id").lower()
        v = _text(el)
        if v:
            out[t] = v
    # 旧式
    for tag in ("id", "imdbid", "tmdbid", "tvdbid"):
        v = _first(root, [tag])
        if v:
            out.setdefault(tag.lower().replace("id", ""), v if tag != "id" else v)
            out.setdefault(tag.lower(), v)
    return out


def parse_nfo(path: Path) -> NfoMeta:
    """
    解析 Kodi / Emby / Jellyfin 共用的 NFO XML。
    支持根节点: movie, episodedetails, episode, tvshow, series, musicvideo 等。
    """
    meta = NfoMeta(source_file=str(path))
    try:
        raw = path.read_text(encoding="utf-8-sig", errors="ignore")
        root = ET.fromstring(raw)
    except Exception:
        return meta

    meta.root_tag = (root.tag or "").lower()

    meta.title = _first(root, ["title", "originaltitle", "sorttitle", "showtitle"])
    meta.plot = _first(root, ["plot", "outline", "tagline", "description"])
    # 多个 studio 时取第一个非空
    studios = []
    for el in root.iter("studio"):
        t = _text(el)
        if t and t not in studios:
            studios.append(t)
    meta.studio = studios[0] if studios else ""

    meta.aired = _first(root, ["aired", "premiered", "releasedate", "dateadded"])
    year_s = _first(root, ["year"])
    if year_s.isdigit():
        meta.year = int(year_s)
    elif meta.aired:
        ym = re.match(r"(\d{4})", meta.aired)
        if ym:
            meta.year = int(ym.group(1))

    meta.rating = _rating_from_nfo(root)
    meta.runtime = _runtime_from_nfo(root)

    actors: list[str] = []
    for actor in root.iter("actor"):
        name_el = actor.find("name")
        name = _text(name_el) if name_el is not None else _text(actor)
        if name and name not in actors:
            actors.append(name)
    meta.actors = actors

    genres: list[str] = []
    for tag in ("genre", "tag", "style"):
        for g in root.iter(tag):
            # 避免把 <tagline> 当类型：iter("tag") 不会匹配 tagline
            if g.tag.lower() != tag:
                continue
            name = _text(g)
            if name and name not in genres:
                genres.append(name)
    meta.genres = genres

    uids = _unique_ids(root)
    # 番号优先：uniqueid type=num / general，再从标题提取
    code = (
        uids.get("num")
        or uids.get("general")
        or extract_code(meta.title)
        or extract_code(path.stem)
        or extract_code(uids.get("id", ""))
    )
    meta.code = (code or "").upper()
    return meta


def prefer_nfo(folder: Path, media_stem: str) -> Path | None:
    """same-stem > movie.nfo > folder.nfo > 任意 episode nfo（跳过 tvshow.nfo）。"""
    candidates = [
        folder / f"{media_stem}.nfo",
        folder / "movie.nfo",
        folder / f"{folder.name}.nfo",
    ]
    for c in candidates:
        if c.is_file():
            return c
    nfos = sorted(
        p
        for p in folder.glob("*.nfo")
        if p.name.lower() not in ("tvshow.nfo", "season.nfo", "series.nfo")
    )
    return nfos[0] if nfos else None


def prefer_poster(folder: Path, media_stem: str) -> Path | None:
    names = [
        f"{media_stem}-poster.jpg",
        f"{media_stem}-poster.jpeg",
        f"{media_stem}-poster.png",
        f"{media_stem}.jpg",
        f"{media_stem}.jpeg",
        f"{media_stem}.png",
        "poster.jpg",
        "poster.jpeg",
        "poster.png",
        "folder.jpg",
        "cover.jpg",
        f"{folder.name}-poster.jpg",
        f"{folder.name}.jpg",
        "fanart.jpg",
        f"{media_stem}-fanart.jpg",
        "backdrop.jpg",
        "thumb.jpg",
    ]
    for name in names:
        c = folder / name
        if c.is_file():
            return c
    for p in sorted(folder.glob("*-poster.*")):
        if p.suffix.lower() in IMAGE_EXTS:
            return p
    for p in sorted(folder.iterdir()):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            return p
    return None


def read_strm(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line
    except Exception:
        pass
    return ""


def is_http_url(url: str) -> bool:
    u = (url or "").strip().lower()
    return u.startswith("http://") or u.startswith("https://")


def media_content_type(path: Path) -> str:
    return {
        ".mp4": "video/mp4",
        ".m4v": "video/mp4",
        ".mkv": "video/x-matroska",
        ".webm": "video/webm",
        ".avi": "video/x-msvideo",
        ".mov": "video/quicktime",
        ".ts": "video/mp2t",
        ".m2ts": "video/mp2t",
        ".mpg": "video/mpeg",
        ".mpeg": "video/mpeg",
        ".flv": "video/x-flv",
        ".wmv": "video/x-ms-wmv",
    }.get(path.suffix.lower(), "application/octet-stream")


def collect_media_files(
    root: Path,
    video_exts: tuple[str, ...] | list[str] | None = None,
) -> list[Path]:
    """
    收集媒体文件。同一目录同一 stem 同时有 .strm 与视频时，优先 .strm。
    """
    exts = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in (video_exts or DEFAULT_VIDEO_EXTS)}
    exts.add(".strm")

    best: dict[tuple[str, str], Path] = {}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext not in exts:
            continue
        if p.name.startswith("."):
            continue
        key = (str(p.parent.resolve()), p.stem.lower())
        cur = best.get(key)
        if cur is None:
            best[key] = p
        elif ext == ".strm":
            best[key] = p
        elif cur.suffix.lower() != ".strm":
            # 都是视频：保留已有（先扫到的）
            pass
    return sorted(best.values(), key=lambda x: str(x).lower())
