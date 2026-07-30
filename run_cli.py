#!/usr/bin/env python3
"""DeoVR Library CLI：目录管理 / 扫描 / 改地址 / 启动服务."""

from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path

from deovr_lib.config import (
    APP_DIR,
    DEFAULT_CONFIG,
    DEFAULT_DB,
    DEFAULTS,
    THUMB_CACHE,
    load_config,
    save_config,
)
from deovr_lib.db import Database
from deovr_lib.scanner import scan_all


def _detect_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return ""


def _apply_rewrite_args(cfg: dict, args: argparse.Namespace) -> dict:
    if getattr(args, "rewrite", None) is True:
        cfg["rewrite_localhost_enabled"] = True
    if getattr(args, "no_rewrite", None) is True:
        cfg["rewrite_localhost_enabled"] = False
    if getattr(args, "rewrite_to", None):
        cfg["rewrite_to"] = args.rewrite_to.strip()
        cfg["rewrite_localhost_enabled"] = True
    if getattr(args, "rewrite_from", None):
        from deovr_lib.media import normalize_rewrite_from

        cfg["rewrite_from"] = normalize_rewrite_from(args.rewrite_from)
        cfg["rewrite_localhost_enabled"] = True
    if getattr(args, "resolve_cdn", None) is True:
        cfg["resolve_strm_redirects"] = True
    if getattr(args, "no_resolve_cdn", None) is True:
        cfg["resolve_strm_redirects"] = False
    return cfg


def _add_rewrite_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("自定义改地址（STRM 本机/局域网主机 → rewrite_to）")
    g.add_argument("--rewrite", action="store_true", help="启用改写")
    g.add_argument("--no-rewrite", action="store_true", help="关闭改写")
    g.add_argument("--rewrite-to", metavar="IP", help="目标 IP，如 192.168.0.18（一般只配这个）")
    g.add_argument(
        "--rewrite-from",
        metavar="HOSTS",
        help="可选：额外主机名，逗号分隔；127.0.0.1/192.168.x.x 等会自动改，通常不必填",
    )
    g.add_argument("--resolve-cdn", action="store_true", help="同时解析到 CDN/直链")
    g.add_argument("--no-resolve-cdn", action="store_true", help="关闭 CDN 解析")


def cmd_scan(args: argparse.Namespace) -> int:
    cfg = load_config()
    db = Database(DEFAULT_DB)
    libs = cfg.get("libraries") or []
    if args.path:
        libs = [{"name": args.name or Path(args.path).name, "path": args.path, "kind": args.kind}]
    # 过滤占位路径
    libs = [
        x
        for x in libs
        if isinstance(x, dict)
        and x.get("path")
        and not str(x["path"]).startswith("/path/to/")
    ]
    if not libs:
        print("无有效目录可扫描。")
        print("请先添加真实路径，例如：")
        print('  python run_cli.py library add --path "/Users/你/影片" --name Movies --kind 2d')
        print("  python run_cli.py library list")
        print("  python run_cli.py scan --force")
        return 1

    video_exts = cfg.get("video_extensions")

    def progress(msg: str, cur: int, total: int) -> None:
        print(f"\r{msg} [{cur}/{total}]", end="", flush=True)

    results = scan_all(
        db, libs, force=args.force, video_exts=video_exts, progress=progress
    )
    print()
    ok = 0
    for r in results:
        if r.get("error"):
            print(f"{r['library']}: 失败 — {r['error']}")
            continue
        ok += 1
        print(
            f"{r['library']}: media={r.get('total_media', r.get('total_strm', 0))} "
            f"(strm={r.get('total_strm', 0)} local={r.get('total_local', 0)}) "
            f"+{r['added']} ~{r['updated']} skip={r['skipped']} -{r['removed']} ({r['elapsed']}s)"
        )
    print("总计影片:", db.movie_count())
    return 0 if ok else 1


def cmd_serve(args: argparse.Namespace) -> int:
    from deovr_lib.server import run_server

    cfg = load_config()
    cfg = _apply_rewrite_args(cfg, args)
    if args.host:
        cfg["host"] = args.host
    if args.port:
        cfg["port"] = args.port
    if args.save_config:
        save_config(cfg)
        print("已写入 data/config.json")

    host = cfg.get("host", "0.0.0.0")
    port = int(cfg.get("port", 8765))
    rw = "开" if cfg.get("rewrite_localhost_enabled", True) else "关"
    to = cfg.get("rewrite_to") or "(自动)"
    cdn = "开" if cfg.get("resolve_strm_redirects") else "关"
    lan = _detect_ip() or "127.0.0.1"
    print(f"Starting http://{host}:{port}/")
    print(f"  本机网页: http://127.0.0.1:{port}/")
    print(f"  局域网:   http://{lan}:{port}/")
    print(f"  DeoVR:    http://{lan}:{port}/deovr")
    print(f"  改写: {rw} → {to}  |  CDN解析: {cdn}")
    print(f"  媒体: .strm + {', '.join(cfg.get('video_extensions') or [])}")
    run_server(host=host, port=port)
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    cfg = load_config()
    changed = False

    if args.detect_ip:
        ip = _detect_ip()
        print("detected_ip:", ip or "(failed)")
        if ip:
            cfg["rewrite_to"] = ip
            cfg["rewrite_localhost_enabled"] = True
            changed = True

    before = (
        cfg.get("rewrite_localhost_enabled"),
        cfg.get("rewrite_to"),
        tuple(cfg.get("rewrite_from") or []),
        cfg.get("resolve_strm_redirects"),
        cfg.get("host"),
        cfg.get("port"),
    )
    cfg = _apply_rewrite_args(cfg, args)
    if args.host:
        cfg["host"] = args.host
    if args.port:
        cfg["port"] = args.port
    after = (
        cfg.get("rewrite_localhost_enabled"),
        cfg.get("rewrite_to"),
        tuple(cfg.get("rewrite_from") or []),
        cfg.get("resolve_strm_redirects"),
        cfg.get("host"),
        cfg.get("port"),
    )
    if before != after:
        changed = True

    print("rewrite_localhost_enabled:", cfg.get("rewrite_localhost_enabled"))
    print("rewrite_to:", cfg.get("rewrite_to"))
    print("rewrite_from:", cfg.get("rewrite_from"))
    print("resolve_strm_redirects:", cfg.get("resolve_strm_redirects"))
    print("host:", cfg.get("host"))
    print("port:", cfg.get("port"))
    print("video_extensions:", ", ".join(cfg.get("video_extensions") or []))
    print("libraries:")
    for lib in cfg.get("libraries") or []:
        print(f"  - {lib.get('name')} [{lib.get('kind')}] {lib.get('path')}")

    if changed and not args.show_only:
        save_config(cfg)
        print("已保存 → data/config.json")
    return 0


FIXED_LIB_NAMES = {"2d": "2D", "vr": "VR"}


def _libs_without_kind(libs: list, kind: str) -> list:
    return [x for x in libs if (x.get("kind") or "").lower() != kind]


def _set_fixed_library(cfg: dict, kind: str, path: Path) -> dict:
    """每个 kind 只保留一个固定槽位（名称 2D / VR）。"""
    kind = kind.lower()
    name = FIXED_LIB_NAMES[kind]
    libs = _libs_without_kind(list(cfg.get("libraries") or []), kind)
    # 同时去掉同名旧项
    libs = [x for x in libs if x.get("name") != name]
    libs.append({"name": name, "path": str(path), "kind": kind})
    # 稳定顺序：2D 在前，VR 在后，其它在后
    order = {"2d": 0, "vr": 1}
    libs.sort(key=lambda x: order.get((x.get("kind") or "").lower(), 9))
    cfg["libraries"] = libs
    return cfg


def cmd_library(args: argparse.Namespace) -> int:
    cfg = load_config()
    libs: list = list(cfg.get("libraries") or [])
    action = args.action

    if action == "list":
        if not libs:
            print("(空) 可用: library set-2d / set-vr")
            return 0
        for i, lib in enumerate(libs, 1):
            print(f"{i}. {lib.get('name')} [{lib.get('kind')}] {lib.get('path')}")
        # 固定槽位摘要
        by_kind = {(x.get("kind") or "").lower(): x for x in libs}
        print("--- 固定槽位 ---")
        for k, label in (("2d", "2D"), ("vr", "VR")):
            cur = by_kind.get(k)
            if cur:
                print(f"  {label}: {cur.get('path')}")
            else:
                print(f"  {label}: (未设置)")
        return 0

    if action in ("set-2d", "set-vr"):
        kind = "2d" if action == "set-2d" else "vr"
        path = Path(args.path).expanduser().resolve()
        if not path.is_dir():
            print(f"目录不存在: {path}")
            return 1
        cfg = _set_fixed_library(cfg, kind, path)
        save_config(cfg)
        print(f"已设置固定{FIXED_LIB_NAMES[kind]}目录: {path}")
        return 0

    if action in ("clear-2d", "clear-vr"):
        kind = "2d" if action == "clear-2d" else "vr"
        name = FIXED_LIB_NAMES[kind]
        before = len(libs)
        libs = [
            x
            for x in libs
            if (x.get("kind") or "").lower() != kind and x.get("name") != name
        ]
        if len(libs) == before:
            print(f"固定{name}目录未设置")
            return 1
        cfg["libraries"] = libs
        save_config(cfg)
        print(f"已清除固定{name}目录")
        return 0

    if action == "add":
        path = Path(args.path).expanduser().resolve()
        if not path.is_dir():
            print(f"目录不存在: {path}")
            return 1
        name = args.name or path.name
        kind = args.kind
        # 同名覆盖
        libs = [x for x in libs if x.get("name") != name]
        libs.append({"name": name, "path": str(path), "kind": kind})
        cfg["libraries"] = libs
        save_config(cfg)
        print(f"已添加: {name} [{kind}] {path}")
        return 0

    if action == "remove":
        before = len(libs)
        libs = [x for x in libs if x.get("name") != args.name and x.get("path") != args.name]
        if len(libs) == before:
            print(f"未找到: {args.name}")
            return 1
        cfg["libraries"] = libs
        save_config(cfg)
        print(f"已移除: {args.name}")
        return 0

    print("未知操作")
    return 1


def cmd_init(args: argparse.Namespace) -> int:
    reset = bool(getattr(args, "reset", False) or getattr(args, "force", False))

    if reset:
        # 清空配置、数据库、封面缓存，回到全新状态
        removed: list[str] = []
        for p in (
            DEFAULT_CONFIG,
            DEFAULT_DB,
            Path(str(DEFAULT_DB) + "-wal"),
            Path(str(DEFAULT_DB) + "-shm"),
        ):
            if p.exists():
                p.unlink()
                removed.append(p.name)
        if THUMB_CACHE.is_dir():
            n = 0
            for f in THUMB_CACHE.glob("*"):
                if f.is_file():
                    f.unlink()
                    n += 1
            removed.append(f"thumbs/* ({n} files)")

        cfg = dict(DEFAULTS)
        ip = _detect_ip()
        if ip:
            cfg["rewrite_to"] = ip
        cfg["libraries"] = []
        save_config(cfg)
        # 重建空库
        Database(DEFAULT_DB)
        print("已重置全部本地数据")
        for x in removed:
            print(f"  删除: {x}")
        print(f"  新配置: {DEFAULT_CONFIG}")
        print(f"  新数据库: {DEFAULT_DB}")
        print("rewrite_to:", cfg.get("rewrite_to"))
        print("libraries: 0")
        print()
        print("下一步：")
        print('  python run_cli.py library add --path "/本机真实目录" --name AV-2D --kind 2d')
        print("  python run_cli.py scan --force")
        print("  python run_cli.py serve --rewrite --rewrite-to <局域网IP>")
        return 0

    cfg = load_config()
    ip = _detect_ip()
    if ip and not cfg.get("rewrite_to"):
        cfg["rewrite_to"] = ip
    cfg.setdefault("rewrite_localhost_enabled", True)
    # 清掉示例占位目录，避免 scan 去扫 /path/to/Movies
    libs = cfg.get("libraries") or []
    cleaned = [
        x
        for x in libs
        if isinstance(x, dict)
        and x.get("path")
        and not str(x["path"]).startswith("/path/to/")
    ]
    if cleaned != libs:
        cfg["libraries"] = cleaned
    save_config(cfg)
    print("已写入默认配置（未清空片库数据库）")
    print("rewrite_to:", cfg.get("rewrite_to"))
    print("libraries:", len(cfg.get("libraries") or []))
    print("video_extensions:", ", ".join(cfg.get("video_extensions") or []))
    print()
    print("若要清空全部旧配置/数据库，请用：")
    print("  python run_cli.py init --reset")
    print()
    print("下一步添加真实片库目录，例如：")
    print('  python run_cli.py library add --path "/Users/你/影片" --name Movies --kind 2d')
    print("  python run_cli.py scan")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """用仓库自带 testdata 搭一套空白可测环境（会 --reset）。"""
    testdata = APP_DIR / "testdata"
    movies = testdata / "Movies"
    movies_vr = testdata / "Movies-VR"
    if not movies.is_dir() or not movies_vr.is_dir():
        print(f"缺少示例数据目录: {testdata}")
        print("请确认仓库含 testdata/Movies 与 testdata/Movies-VR")
        return 1

    # 复用 init --reset
    ns = argparse.Namespace(reset=True)
    cmd_init(ns)

    cfg = load_config()
    cfg["libraries"] = [
        {"name": "Movies", "path": str(movies.resolve()), "kind": "2d"},
        {"name": "Movies-VR", "path": str(movies_vr.resolve()), "kind": "vr"},
    ]
    ip = _detect_ip()
    if ip:
        cfg["rewrite_to"] = ip
        cfg["rewrite_localhost_enabled"] = True
    save_config(cfg)

    scan_ns = argparse.Namespace(path=None, name="", kind="2d", force=True)
    code = cmd_scan(scan_ns)
    if code != 0:
        return code

    print()
    print("Demo 就绪。可启动：")
    print("  python run_cli.py serve --port 8765")
    print("网页: http://127.0.0.1:8765/browse")
    print("DeoVR JSON: http://127.0.0.1:8765/deovr?format=json")
    if not args.serve:
        return 0

    serve_ns = argparse.Namespace(
        host=None,
        port=args.port,
        save_config=False,
        rewrite=True,
        no_rewrite=False,
        rewrite_to=cfg.get("rewrite_to"),
        rewrite_from=None,
        resolve_cdn=False,
        no_resolve_cdn=False,
    )
    return cmd_serve(serve_ns)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="DeoVR Library CLI（支持 .strm 与本地视频 + Emby/Jellyfin NFO）"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="扫描媒体入库（.strm / mp4 / mkv … + NFO）")
    s.add_argument("--path", help="单目录路径（覆盖配置）")
    s.add_argument("--name", default="", help="目录显示名")
    s.add_argument("--kind", choices=["2d", "vr"], default="2d")
    s.add_argument("--force", action="store_true", help="强制全量重扫")
    s.set_defaults(func=cmd_scan)

    v = sub.add_parser("serve", help="启动 HTTP 服务")
    v.add_argument("--host", default=None)
    v.add_argument("--port", type=int, default=None)
    v.add_argument("--save-config", action="store_true", help="写入 config.json")
    _add_rewrite_args(v)
    v.set_defaults(func=cmd_serve)

    c = sub.add_parser("config", help="查看/设置改地址与端口")
    c.add_argument("--show", action="store_true")
    c.add_argument("--show-only", action="store_true", help="只显示不保存")
    c.add_argument("--detect-ip", action="store_true")
    c.add_argument("--host", default=None)
    c.add_argument("--port", type=int, default=None)
    _add_rewrite_args(c)
    c.set_defaults(func=cmd_config)

    lib = sub.add_parser("library", help="媒体目录管理（含固定 2D/VR 槽位）")
    lib_sub = lib.add_subparsers(dest="action", required=True)
    lib_sub.add_parser("list", help="列出目录").set_defaults(func=cmd_library, action="list")

    la = lib_sub.add_parser("add", help="添加目录（可多个）")
    la.add_argument("--path", required=True)
    la.add_argument("--name", default="")
    la.add_argument("--kind", choices=["2d", "vr"], default="2d")
    la.set_defaults(func=cmd_library, action="add")

    lr = lib_sub.add_parser("remove", help="按名称或路径移除")
    lr.add_argument("name", help="目录 name 或 path")
    lr.set_defaults(func=cmd_library, action="remove")

    s2 = lib_sub.add_parser("set-2d", help="设置/覆盖固定 2D 目录")
    s2.add_argument("--path", required=True)
    s2.set_defaults(func=cmd_library, action="set-2d")

    sv = lib_sub.add_parser("set-vr", help="设置/覆盖固定 VR 目录")
    sv.add_argument("--path", required=True)
    sv.set_defaults(func=cmd_library, action="set-vr")

    lib_sub.add_parser("clear-2d", help="清除固定 2D 目录").set_defaults(
        func=cmd_library, action="clear-2d"
    )
    lib_sub.add_parser("clear-vr", help="清除固定 VR 目录").set_defaults(
        func=cmd_library, action="clear-vr"
    )

    i = sub.add_parser("init", help="写入默认配置；--reset 清空全部本地数据后重建")
    i.add_argument(
        "--reset",
        "--force",
        dest="reset",
        action="store_true",
        help="删除 config.json / library.db / thumbs，写入全新空配置",
    )
    i.set_defaults(func=cmd_init)

    d = sub.add_parser("demo", help="用 testdata 重置并扫描空白示例片库（适合 GitHub 测试）")
    d.add_argument("--serve", action="store_true", help="扫描后直接启动服务")
    d.add_argument("--port", type=int, default=8765)
    d.set_defaults(func=cmd_demo)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
