from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from .classify import detect_kind, detect_region
from .db import Database
from .nfo import (
    DEFAULT_VIDEO_EXTS,
    collect_media_files,
    extract_code,
    parse_nfo,
    prefer_nfo,
    prefer_poster,
    read_strm,
)


def collect_bare_strm(
    libraries: list[dict[str, Any]],
    *,
    video_exts: list[str] | None = None,
) -> list[dict[str, Any]]:
    """收集无同名 NFO 且无同名封面的 .strm（按磁盘 sidecar 严格判断）。"""
    exts = tuple(video_exts) if video_exts else DEFAULT_VIDEO_EXTS
    out: list[dict[str, Any]] = []
    for lib in libraries:
        root_s = (lib.get("path") or "").strip()
        if not root_s:
            continue
        root = Path(root_s).expanduser()
        if not root.is_dir():
            continue
        lib_name = lib.get("name") or root.name
        for media in collect_media_files(root, exts):
            if media.suffix.lower() != ".strm":
                continue
            folder = media.parent
            has_nfo = prefer_nfo(folder, media.stem) is not None
            has_poster = prefer_poster(folder, media.stem) is not None
            if has_nfo or has_poster:
                continue
            try:
                rel = str(media.resolve().relative_to(root.resolve()))
            except ValueError:
                rel = media.name
            out.append(
                {
                    "library": lib_name,
                    "root": str(root.resolve()),
                    "rel": rel.replace("\\", "/"),
                    "path": str(media.resolve()),
                    "name": media.name,
                }
            )
    out.sort(key=lambda x: (x["library"], x["rel"].lower()))
    return out


def format_bare_strm_tree(items: list[dict[str, Any]]) -> str:
    """把裸 strm 列表格式化为可读的文件名树。"""
    lines: list[str] = [
        "# 无同名 NFO 且无同名封面的 .strm",
        "# 匹配规则：仅 {stem}.nfo / {stem}-poster.* / {stem}.* 等 sidecar",
        f"# 共 {len(items)} 个",
        "",
    ]
    if not items:
        lines.append("(无)")
        lines.append("")
        return "\n".join(lines)

    current_lib: str | None = None
    seen_dirs: set[str] = set()
    for it in items:
        lib = it["library"]
        if lib != current_lib:
            if current_lib is not None:
                lines.append("")
            current_lib = lib
            seen_dirs = set()
            lines.append(f"[{lib}]")
            lines.append(f"  root: {it['root']}")
        parts = [p for p in it["rel"].split("/") if p]
        if not parts:
            continue
        for i in range(len(parts) - 1):
            dkey = "/".join(parts[: i + 1])
            if dkey in seen_dirs:
                continue
            seen_dirs.add(dkey)
            lines.append("  " * (i + 1) + f"{parts[i]}/")
        depth = max(0, len(parts) - 1)
        lines.append("  " * (depth + 1) + parts[-1])
    lines.append("")
    return "\n".join(lines)

ProgressCb = Callable[[str, int, int], None]


def _mtime(path: Path | None) -> float | None:
    if not path or not path.exists():
        return None
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def scan_library(
    db: Database,
    *,
    name: str,
    path: str,
    kind: str = "2d",
    force: bool = False,
    video_exts: list[str] | None = None,
    progress: ProgressCb | None = None,
) -> dict[str, Any]:
    root = Path(path)
    if not root.is_dir():
        raise FileNotFoundError(f"目录不存在: {path}")

    lib_id = db.upsert_library(name, str(root), kind)
    exts = tuple(video_exts) if video_exts else DEFAULT_VIDEO_EXTS
    if progress:
        progress(f"枚举文件: {name} …", 0, 0)
    media_files = collect_media_files(root, exts)
    total = len(media_files)
    if progress:
        progress(f"开始入库 {name}（共 {total}）", 0, max(total, 1))
    added = updated = skipped = 0
    keep: set[str] = set()
    t0 = time.time()
    by_type = {"strm": 0, "local": 0}

    existing: dict[str, tuple[int, float | None, float | None]] = {}
    with db.session() as conn:
        for r in conn.execute(
            "SELECT id, strm_path, strm_mtime, nfo_mtime FROM movies WHERE library_id=?",
            (lib_id,),
        ).fetchall():
            existing[r["strm_path"]] = (int(r["id"]), r["strm_mtime"], r["nfo_mtime"])

    for i, media in enumerate(media_files, 1):
        if progress and (i % 5 == 0 or i == total or i == 1):
            progress(f"扫描 {name}: {media.parent.name}", i, total)

        media_path = str(media.resolve())
        keep.add(media_path)
        folder = media.parent
        media_mt = _mtime(media)
        nfo_path = prefer_nfo(folder, media.stem)
        nfo_mt = _mtime(nfo_path)

        if not force and media_path in existing:
            _, old_s, old_n = existing[media_path]
            if old_s == media_mt and old_n == nfo_mt:
                skipped += 1
                continue

        if media.suffix.lower() == ".strm":
            url = read_strm(media)
            by_type["strm"] += 1
        else:
            url = ""
            by_type["local"] += 1

        # 仅使用同名 sidecar；无同名 NFO/图则留空，绝不借用文件夹内其它影片资料
        meta = parse_nfo(nfo_path) if nfo_path else None
        title = (meta.title if meta and meta.title else "") or media.stem
        code = (meta.code if meta and meta.code else "") or extract_code(media.stem)
        poster = prefer_poster(folder, media.stem)

        actors = list(meta.actors) if meta else []
        genres = list(meta.genres) if meta else []

        studio = (meta.studio if meta else "") or ""
        # 2D/VR、日本/欧美一律由 NFO/番号/片商识别，不再回退到目录 kind
        movie_kind = detect_kind(
            genres=genres, title=title, path=media_path, studio=studio
        )
        region = detect_region(
            code=code or "",
            title=title,
            folder=folder.name,
            path=media_path,
        )

        is_new = media_path not in existing
        db.upsert_movie(
            library_id=lib_id,
            code=code or "",
            title=title,
            plot=meta.plot if meta else "",
            studio=studio,
            year=meta.year if meta else None,
            aired=meta.aired if meta else "",
            rating=meta.rating if meta else None,
            runtime=meta.runtime if meta else None,
            kind=movie_kind,
            region=region,
            strm_path=media_path,
            strm_url=url,
            poster_path=str(poster) if poster else None,
            nfo_path=str(nfo_path) if nfo_path else None,
            nfo_mtime=nfo_mt,
            strm_mtime=media_mt,
            folder_name=folder.name,
            actors=actors,
            genres=genres,
        )
        if is_new:
            added += 1
        else:
            updated += 1

    removed = db.remove_missing(lib_id, keep)
    return {
        "library": name,
        "path": str(root),
        "kind": kind,
        "total_media": total,
        "total_strm": by_type["strm"],
        "total_local": by_type["local"],
        "added": added,
        "updated": updated,
        "skipped": skipped,
        "removed": removed,
        "elapsed": round(time.time() - t0, 2),
    }


def scan_all(
    db: Database,
    libraries: list[dict[str, Any]],
    *,
    force: bool = False,
    video_exts: list[str] | None = None,
    progress: ProgressCb | None = None,
) -> list[dict[str, Any]]:
    results = []
    for lib in libraries:
        path = (lib.get("path") or "").strip()
        if not path:
            continue
        name = lib.get("name") or Path(path).name
        if path.startswith("/path/to/") or not Path(path).is_dir():
            print(f"\n跳过「{name}」: 目录不存在 → {path}")
            print("  请先: python run_cli.py library set-mixed --path 真实目录")
            results.append(
                {
                    "library": name,
                    "total_media": 0,
                    "total_strm": 0,
                    "total_local": 0,
                    "added": 0,
                    "updated": 0,
                    "skipped": 0,
                    "removed": 0,
                    "elapsed": 0,
                    "error": f"目录不存在: {path}",
                }
            )
            continue
        results.append(
            scan_library(
                db,
                name=name,
                path=path,
                kind=lib.get("kind") or "mixed",
                force=force,
                video_exts=video_exts,
                progress=progress,
            )
        )
    return results
