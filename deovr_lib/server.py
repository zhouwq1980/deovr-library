from __future__ import annotations

import socket
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
import json as _json
from starlette.middleware.base import BaseHTTPMiddleware

from .config import load_config
from .db import Database
from .media import (
    is_private_or_loopback_host,
    normalize_rewrite_from,
    resolve_media_url,
    rewrite_loopback,
)
from .nfo import is_http_url, media_content_type, read_strm
from .thumbs import ensure_thumb, thumb_cache_token

WEB_DIR = Path(__file__).parent / "web"
_jinja = Environment(
    loader=FileSystemLoader(str(WEB_DIR / "templates")),
    autoescape=select_autoescape(["html", "xml"]),
    cache_size=0,
)
_jinja.filters["tojson"] = lambda v: _json.dumps(v, ensure_ascii=False)
# 在 script 里输出 JSON 时需 |safe，避免 &#34; 转义弄坏 JS


def _render(name: str, **ctx: Any) -> HTMLResponse:
    return HTMLResponse(_jinja.get_template(name).render(**ctx))


def _detect_lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return ""


class CorsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            resp = Response(status_code=204)
        else:
            resp = await call_next(request)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, HEAD, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "*"
        return resp


class DeoJSONResponse(JSONResponse):
    """UTF-8 JSON，带 charset，避免 DeoVR/浏览器把中文当 Latin-1 显示成乱码。"""

    media_type = "application/json; charset=utf-8"

    def render(self, content: Any) -> bytes:
        return _json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
        ).encode("utf-8")


def create_app(db: Database | None = None, cfg: dict[str, Any] | None = None) -> FastAPI:
    database = db or Database()
    config = cfg or load_config()
    app = FastAPI(title="DeoVR Library", version="1.0.0")
    app.state.db = database
    app.state.cfg = config
    app.add_middleware(CorsMiddleware)

    static_dir = WEB_DIR / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    def base_url(request: Request) -> str:
        """给头显/外网用的绝对根地址：优先 rewrite_to，避免 JSON 里出现 127.0.0.1。"""
        proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
        cfg_l = app.state.cfg
        port = int(cfg_l.get("port") or 8765)
        host_hdr = (request.headers.get("host") or "").strip()
        if host_hdr:
            # host:port（忽略 IPv6 特例，本服务主要用于 IPv4 局域网）
            if host_hdr.count(":") == 1:
                _h, p = host_hdr.rsplit(":", 1)
                if p.isdigit():
                    port = int(p)

        if cfg_l.get("rewrite_localhost_enabled", True):
            lan = (
                str(cfg_l.get("rewrite_to") or "").strip()
                or str(cfg_l.get("lan_host") or "").strip()
                or _detect_lan_ip()
            )
            if lan:
                return f"{proto}://{lan}:{port}"

        if host_hdr:
            name = host_hdr.split(":")[0].lower()
            if name not in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
                return f"{proto}://{host_hdr}"
            detected = _detect_lan_ip()
            if detected:
                return f"{proto}://{detected}:{port}"
            return f"{proto}://{host_hdr}"

        detected = _detect_lan_ip()
        return f"{proto}://{(detected or '127.0.0.1')}:{port}"

    def rewrite_target(request: Request) -> str:
        """自定义改地址目标 IP（rewrite_to）；未填则用请求 Host / 自动检测。"""
        try:
            cfg_l = load_config()
            app.state.cfg = cfg_l
        except Exception:
            cfg_l = app.state.cfg
        if not cfg_l.get("rewrite_localhost_enabled", True):
            return ""
        custom = str(cfg_l.get("rewrite_to") or "").strip()
        if custom:
            return custom
        # 兼容旧字段 lan_host
        legacy = str(cfg_l.get("lan_host") or "").strip()
        if legacy:
            return legacy
        host = request.headers.get("host") or ""
        name = host.split(":")[0].strip()
        if name and name not in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
            return name
        return _detect_lan_ip()

    def strm_raw_url(movie: dict[str, Any]) -> str:
        strm_path = movie.get("strm_path")
        url = ""
        if strm_path and Path(strm_path).is_file():
            p = Path(strm_path)
            if p.suffix.lower() == ".strm":
                url = read_strm(p)
            else:
                # 本地视频：播放时由 /play/{id} 直接 Range 输出文件
                return ""
        return url or (movie.get("strm_url") or "")

    def is_local_media(movie: dict[str, Any]) -> bool:
        p = movie.get("strm_path") or ""
        if not p:
            return False
        path = Path(p)
        return path.is_file() and path.suffix.lower() != ".strm" and not is_http_url(
            movie.get("strm_url") or ""
        )

    def media_url_for_client(request: Request, movie: dict[str, Any]) -> str:
        """头显可访问的播放地址：本地文件走本服务 /play；STRM 改写后直链（可再解析 CDN）。"""
        bu = base_url(request)
        if is_local_media(movie):
            return f"{bu}/play/{movie['id']}"

        raw = strm_raw_url(movie)
        if not raw:
            return ""
        try:
            cfg_l = load_config()
            app.state.cfg = cfg_l
        except Exception:
            cfg_l = app.state.cfg
        target = rewrite_target(request)
        from_hosts = cfg_l.get("rewrite_from")
        url = raw

        # 跟随跳转到最终直链/CDN：
        # - 配置显式开启；或
        # - STRM 仍是回环/私网网关时自动解析（否则只改 IP 头显仍可能打不开仅监听 127.0.0.1 的网关）
        do_resolve = bool(cfg_l.get("resolve_strm_redirects", False))
        if not do_resolve and bool(cfg_l.get("auto_resolve_private_strm", True)):
            host = (urlparse(raw).hostname or "").lower()
            # 本机/局域网播放网关：服务端跟随到 CDN 直链（仅改 IP 往往不够）
            if is_private_or_loopback_host(host):
                do_resolve = True
        if do_resolve:
            # 服务端用原始地址跟随（本机可访问 127.0.0.1）；终态若仍是私网再改写
            url = resolve_media_url(
                raw,
                lan_host=target,
                rewrite_from=from_hosts,
                ttl=int(cfg_l.get("media_url_cache_ttl") or 300),
            )
        if cfg_l.get("rewrite_localhost_enabled", True) and target:
            url = rewrite_loopback(url, target, rewrite_from=from_hosts)
        return url

    def video_detail(request: Request, movie: dict[str, Any]) -> dict[str, Any]:
        try:
            cfg_l = load_config()
            app.state.cfg = cfg_l
        except Exception:
            cfg_l = app.state.cfg
        is_vr = movie.get("kind") == "vr"
        runtime_min = movie.get("runtime") or 0
        video_length = int(runtime_min) * 60 if runtime_min else 0
        mid = movie["id"]
        bu = base_url(request)
        screen = cfg_l["vr_screen_type"] if is_vr else cfg_l["flat_screen_type"]
        stereo = cfg_l["vr_stereo_mode"] if is_vr else cfg_l["flat_stereo_mode"]
        thumb = f"{bu}/cover/{mid}.jpg"
        # STRM：JSON 里直接给改写后的直链（避免头显不跟 /play 的 302，或仍看到 127.0.0.1）
        # 本地文件：仍走本服务 /play
        play = media_url_for_client(request, movie) or f"{bu}/play/{mid}"
        return {
            "id": mid,
            "title": movie.get("title") or movie.get("code") or f"#{mid}",
            "authorized": 1,
            "description": movie.get("plot") or "",
            "is3d": True,
            "screenType": screen,
            "stereoMode": stereo,
            "skipIntro": 0,
            "videoLength": video_length,
            "thumbnailUrl": thumb,
            "fullVideoReady": True,
            "fullAccess": True,
            "actors": [{"id": i + 1, "name": n} for i, n in enumerate(movie.get("actors") or [])],
            "categories": [
                {"tag": {"id": int(g["id"]), "name": g["name"]}}
                for g in (movie.get("genres") or [])
                if isinstance(g, dict) and g.get("name")
            ],
            "paysite": {
                "id": 1,
                "name": movie.get("studio") or movie.get("library_name") or "",
                "is3rdParty": True,
            },
            "encodings": [
                {
                    "name": "h264",
                    "videoSources": [
                        {
                            "resolution": int(cfg_l.get("default_resolution") or 2160),
                            "url": play,
                        }
                    ],
                }
            ],
        }

    def deovr_list_item(request: Request, m: dict[str, Any]) -> dict[str, Any]:
        bu = base_url(request)
        return {
            "title": m["title"],
            "id": m["id"],
            "videoLength": int(m["runtime"] or 0) * 60,
            "thumbnailUrl": f"{bu}/cover/{m['id']}.jpg",
            "video_url": f"{bu}/deovr/{m['id']}",
        }

    def deovr_scene_from_movies(
        request: Request, name: str, items: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return {
            "authorized": "1",
            "scenes": [
                {
                    "name": name,
                    "list": [deovr_list_item(request, m) for m in items],
                }
            ],
        }

    def render_index(init: dict[str, Any] | None = None) -> HTMLResponse:
        stats = database.stats()
        return _render(
            "index.html",
            stats=stats,
            libraries=database.list_libraries(),
            page_size=config.get("page_size", 48),
            init_filters=init or {},
        )

    def wants_deovr_json(request: Request) -> bool:
        """根路径 POST 等是否返回片库 JSON。"""
        if request.method in ("POST", "OPTIONS"):
            return True
        ua = (request.headers.get("user-agent") or "").lower()
        accept = (request.headers.get("accept") or "").lower()
        if "deovr" in ua or "deo vr" in ua or "heresphere" in ua:
            return True
        if "application/json" in accept and "text/html" not in accept:
            return True
        return False

    def wants_html_guide(request: Request) -> bool:
        """内置浏览器地址栏打开 /deovr 时，给引导页而不是裸 JSON 文本。"""
        if request.method != "GET":
            return False
        fmt = (request.query_params.get("format") or "").lower()
        if fmt in ("json", "1", "raw") or request.query_params.get("json") in (
            "1",
            "true",
            "yes",
        ):
            return False
        ua = (request.headers.get("user-agent") or "").lower()
        if "deovr" in ua or "deo vr" in ua or "heresphere" in ua:
            return False
        accept = (request.headers.get("accept") or "").lower()
        return "text/html" in accept

    def deo_json(data: dict[str, Any]) -> DeoJSONResponse:
        return DeoJSONResponse(
            data,
            headers={
                "Cache-Control": "no-store",
                "Access-Control-Allow-Origin": "*",
            },
        )

    def build_deovr_library(
        request: Request,
        *,
        kind: str | None = None,
        genre: str | None = None,
        actor: str | None = None,
        studio: str | None = None,
        library_id: int | None = None,
    ) -> dict[str, Any]:
        """DeoVR Selection Scene JSON。

        重要：DeoVR 不支持 video_url 指向二级片库（点了会退回主页）。
        因此筛选只能做成底栏 Tab，每个 Tab 直接放影片列表。
        """
        cfg_l = load_config()
        app.state.cfg = cfg_l
        limit = int(cfg_l.get("deovr_section_limit") or 200)
        # 底栏 Tab 总数宜少，过多会异常
        genre_tabs = int(cfg_l.get("deovr_genre_tabs") or 8)
        actor_tabs = int(cfg_l.get("deovr_actor_tabs") or 0)

        if genre:
            items = database.search_movies(genre=genre, page=1, page_size=limit)["items"]
            return deovr_scene_from_movies(request, genre, items)

        if actor:
            items = database.search_movies(actor=actor, page=1, page_size=limit)["items"]
            return deovr_scene_from_movies(request, actor, items)

        if studio:
            items = database.search_movies(studio=studio, page=1, page_size=limit)["items"]
            return deovr_scene_from_movies(request, studio, items)

        if kind:
            items = database.list_for_deovr(kind=kind, limit=limit)
            label = {"2d": "2D", "vr": "VR"}.get(kind, kind.upper())
            return deovr_scene_from_movies(request, label, items)

        if library_id:
            lib_name = next(
                (x["name"] for x in database.list_libraries() if x["id"] == library_id),
                f"Lib {library_id}",
            )
            items = database.list_for_deovr(library_id=library_id, limit=limit)
            return deovr_scene_from_movies(request, lib_name, items)

        scenes: list[dict[str, Any]] = []

        recent = database.list_for_deovr(limit=min(100, limit))
        scenes.append(
            {"name": "Recent", "list": [deovr_list_item(request, m) for m in recent]}
        )

        for lib in database.list_libraries():
            items = database.list_for_deovr(library_id=lib["id"], limit=min(120, limit))
            if items:
                scenes.append(
                    {
                        "name": lib["name"][:24],
                        "list": [deovr_list_item(request, m) for m in items],
                    }
                )

        for k, label in (("2d", "2D"), ("vr", "VR")):
            items = database.list_for_deovr(kind=k, limit=min(100, limit))
            if items:
                scenes.append(
                    {"name": label, "list": [deovr_list_item(request, m) for m in items]}
                )

        # 热门类型：每个类型一个底栏 Tab（直接出片，禁止文件夹套娃）
        for g in database.facet_genres(genre_tabs):
            gname = g["name"]
            items = database.search_movies(
                genre=gname, page=1, page_size=min(80, limit)
            )["items"]
            if items:
                # Tab 名尽量短；完整名在列表里用片标题体现
                tab = gname if len(gname) <= 12 else (gname[:11] + "…")
                scenes.append(
                    {"name": tab, "list": [deovr_list_item(request, m) for m in items]}
                )

        if actor_tabs > 0:
            for a in database.facet_actors(actor_tabs):
                aname = a["name"]
                items = database.search_movies(
                    actor=aname, page=1, page_size=min(60, limit)
                )["items"]
                if items:
                    tab = aname if len(aname) <= 12 else (aname[:11] + "…")
                    scenes.append(
                        {
                            "name": tab,
                            "list": [deovr_list_item(request, m) for m in items],
                        }
                    )

        return {"authorized": "1", "scenes": scenes}

    @app.api_route("/", methods=["GET", "POST", "HEAD", "OPTIONS"])
    async def index(request: Request):
        # GET 一律进网页片库，避免点分类后落到 / 时被 DeoVR UA 当成 JSON 主页
        # DeoVR 片库请走 /deovr；仅 POST（登录态）仍回 JSON
        if request.method in ("POST", "OPTIONS"):
            return deo_json(build_deovr_library(request))
        return RedirectResponse(url="/browse", status_code=302)

    @app.get("/open", response_class=HTMLResponse)
    @app.get("/deovr/open", response_class=HTMLResponse)
    async def deovr_open_page(request: Request):
        json_url = f"{base_url(request)}/deovr"
        return _render("deovr_open.html", json_url=json_url)

    @app.get("/browse", response_class=HTMLResponse)
    async def browse_home(request: Request):
        # 从 query 注入初始筛选（详情页分类标签跳转依赖此）
        init: dict[str, Any] = {}
        for key in ("q", "kind", "library_id", "sort", "actor", "genre", "studio"):
            val = request.query_params.get(key)
            if val is not None and str(val).strip() != "":
                init[key] = unquote(str(val))
        return render_index(init or None)

    @app.get("/genre/{name:path}", response_class=HTMLResponse)
    async def browse_genre(name: str):
        # 兼容旧链接 → 统一到 /browse?genre=
        return RedirectResponse(
            url=f"/browse?genre={quote(unquote(name), safe='')}",
            status_code=302,
        )

    @app.get("/actor/{name:path}", response_class=HTMLResponse)
    async def browse_actor(name: str):
        return RedirectResponse(
            url=f"/browse?actor={quote(unquote(name), safe='')}",
            status_code=302,
        )

    @app.get("/kind/{name}", response_class=HTMLResponse)
    async def browse_kind(name: str):
        k = name.lower().strip()
        if k not in ("2d", "vr"):
            raise HTTPException(404)
        return RedirectResponse(url=f"/browse?kind={k}", status_code=302)

    @app.get("/m/{movie_id}", response_class=HTMLResponse)
    async def movie_page(request: Request, movie_id: int):
        movie = database.get_movie(movie_id)
        if not movie:
            raise HTTPException(404, "未找到影片")
        movie = dict(movie)
        movie["cover_token"] = thumb_cache_token(movie.get("poster_path"), movie_id)
        raw = strm_raw_url(movie)
        play = media_url_for_client(request, movie) or f"{base_url(request)}/play/{movie_id}"
        return _render(
            "detail.html",
            movie=movie,
            base=base_url(request),
            play_url=play,
            raw_url=raw,
            play_changed=bool(raw and play and raw != play),
        )

    @app.get("/api/movies")
    async def api_movies(
        q: str = "",
        actor: str = "",
        genre: str = "",
        studio: str = "",
        kind: str = "",
        library_id: int | None = None,
        year: int | None = None,
        sort: str = "updated",
        page: int = Query(1, ge=1),
        page_size: int = Query(48, ge=1, le=200),
    ):
        data = database.search_movies(
            q=q,
            actor=actor,
            genre=genre,
            studio=studio,
            kind=kind,
            library_id=library_id,
            year=year,
            sort=sort,
            page=page,
            page_size=page_size,
        )
        for item in data.get("items") or []:
            item["cover_token"] = thumb_cache_token(item.get("poster_path"), int(item["id"]))
        return data

    @app.get("/api/facets")
    async def api_facets():
        return {
            "actors": database.facet_actors(300),
            "genres": database.facet_genres(300),
            "studios": database.facet_studios(200),
            "libraries": database.list_libraries(),
            "stats": database.stats(),
        }

    @app.get("/api/stats")
    async def api_stats():
        return database.stats()

    @app.get("/api/movie/{movie_id}")
    async def api_movie(movie_id: int):
        movie = database.get_movie(movie_id)
        if not movie:
            raise HTTPException(404)
        return movie

    def _cover_response(movie_id: int, full: bool) -> FileResponse:
        movie = database.get_movie(movie_id)
        if not movie:
            raise HTTPException(404)
        poster = movie.get("poster_path")
        if not poster or not Path(poster).is_file():
            raise HTTPException(404, "无封面")
        if full:
            path = poster
        else:
            thumb = ensure_thumb(poster, movie_id, int(config.get("thumb_max_width") or 480))
            path = str(thumb) if thumb else poster
        token = thumb_cache_token(poster, movie_id)
        try:
            mtime = Path(path).stat().st_mtime
        except OSError:
            mtime = 0
        return FileResponse(
            path,
            media_type="image/jpeg",
            headers={
                # 列表缩略图易因旧缓存显示错图；用 ETag/短缓存 + 前端 token 防呆
                "Cache-Control": "public, max-age=300, must-revalidate",
                "ETag": f'"{token}-{int(mtime)}-{"f" if full else "t"}"',
                "Access-Control-Allow-Origin": "*",
            },
        )

    @app.api_route("/cover/{movie_id}.jpg", methods=["GET", "HEAD"])
    @app.api_route("/cover/{movie_id}.JPG", methods=["GET", "HEAD"])
    async def cover_jpg(movie_id: int):
        return _cover_response(movie_id, full=True)

    @app.api_route("/cover/{movie_id}", methods=["GET", "HEAD"])
    async def cover(movie_id: int, full: int = 0):
        return _cover_response(movie_id, full=bool(full))

    @app.api_route("/play/{movie_id}", methods=["GET", "HEAD"])
    async def play(request: Request, movie_id: int):
        movie = database.get_movie(movie_id)
        if not movie:
            raise HTTPException(404)

        media_path = movie.get("strm_path") or ""
        path = Path(media_path) if media_path else None

        # 本地视频：直接输出（支持 Range）
        if path and path.is_file() and path.suffix.lower() != ".strm":
            return FileResponse(
                path,
                media_type=media_content_type(path),
                filename=path.name,
                headers={"Access-Control-Allow-Origin": "*"},
            )

        # STRM / HTTP 地址
        raw = ""
        if path and path.is_file() and path.suffix.lower() == ".strm":
            raw = read_strm(path)
        if not raw:
            raw = movie.get("strm_url") or ""
        if not raw or not is_http_url(raw):
            raise HTTPException(404, "无有效播放地址（STRM 为空或本地文件缺失）")

        try:
            cfg_l = load_config()
            app.state.cfg = cfg_l
        except Exception:
            cfg_l = app.state.cfg
        # 与 DeoVR JSON 同一套改写/解析逻辑
        url = media_url_for_client(request, movie)
        if not url or not is_http_url(url):
            raise HTTPException(404, "无有效播放地址（STRM 为空或本地文件缺失）")
        return RedirectResponse(url=url, status_code=302)

    @app.get("/api/resolve/{movie_id}")
    async def api_resolve(request: Request, movie_id: int):
        movie = database.get_movie(movie_id)
        if not movie:
            raise HTTPException(404)
        raw = strm_raw_url(movie)
        target = rewrite_target(request)
        from_hosts = app.state.cfg.get("rewrite_from")
        rewritten = (
            rewrite_loopback(raw, target, rewrite_from=from_hosts)
            if raw and target
            else raw
        )
        final = media_url_for_client(request, movie)
        return {
            "raw": raw,
            "rewritten": rewritten,
            "final": final,
            "changed": bool(raw and final and raw != final),
            "rewrite_enabled": bool(app.state.cfg.get("rewrite_localhost_enabled", True)),
            "rewrite_to": target,
            "rewrite_from": normalize_rewrite_from(app.state.cfg.get("rewrite_from")),
            "rewrite_mode": "auto-private+loopback",
            "resolve_strm_redirects": bool(app.state.cfg.get("resolve_strm_redirects", False)),
        }

    @app.api_route("/deovr", methods=["GET", "POST", "HEAD", "OPTIONS"])
    @app.api_route("/deovr/", methods=["GET", "POST", "HEAD", "OPTIONS"])
    @app.api_route("/deovr.json", methods=["GET", "POST", "HEAD", "OPTIONS"])
    async def deovr_library(request: Request):
        # 浏览器地址栏打开：引导页（避免只看到乱码 JSON 文本）
        # DeoVR 片库引擎 / ?format=json / 专用 UA：返回 JSON
        if wants_html_guide(request) and not request.url.path.endswith("deovr.json"):
            json_url = f"{base_url(request)}/deovr"
            return _render("deovr_open.html", json_url=json_url)
        return deo_json(build_deovr_library(request))

    @app.api_route("/deovr/g/{genre_id}", methods=["GET", "POST", "HEAD", "OPTIONS"])
    async def deovr_by_genre_id(request: Request, genre_id: int):
        name = database.genre_name(genre_id)
        if not name:
            raise HTTPException(404, "类型不存在")
        return deo_json(build_deovr_library(request, genre=name))

    @app.api_route("/deovr/a/{actor_id}", methods=["GET", "POST", "HEAD", "OPTIONS"])
    async def deovr_by_actor_id(request: Request, actor_id: int):
        name = database.actor_name(actor_id)
        if not name:
            raise HTTPException(404, "演员不存在")
        return deo_json(build_deovr_library(request, actor=name))

    @app.api_route("/deovr/kind/{kind}", methods=["GET", "POST", "HEAD", "OPTIONS"])
    async def deovr_by_kind(request: Request, kind: str):
        k = kind.lower().strip()
        if k not in ("2d", "vr"):
            raise HTTPException(404, "kind 仅为 2d 或 vr")
        return deo_json(build_deovr_library(request, kind=k))

    @app.api_route("/deovr/library/{library_id}", methods=["GET", "POST", "HEAD", "OPTIONS"])
    async def deovr_by_library(request: Request, library_id: int):
        return deo_json(build_deovr_library(request, library_id=library_id))

    @app.api_route("/deovr/genre/{name:path}", methods=["GET", "POST", "HEAD", "OPTIONS"])
    async def deovr_by_genre(request: Request, name: str):
        return deo_json(build_deovr_library(request, genre=unquote(name)))

    @app.api_route("/deovr/actor/{name:path}", methods=["GET", "POST", "HEAD", "OPTIONS"])
    async def deovr_by_actor(request: Request, name: str):
        return deo_json(build_deovr_library(request, actor=unquote(name)))

    @app.api_route("/deovr/studio/{name:path}", methods=["GET", "POST", "HEAD", "OPTIONS"])
    async def deovr_by_studio(request: Request, name: str):
        return deo_json(build_deovr_library(request, studio=unquote(name)))

    @app.api_route("/deovr/{movie_id}", methods=["GET", "POST", "OPTIONS"])
    async def deovr_video(request: Request, movie_id: int):
        movie = database.get_movie(movie_id)
        if not movie:
            raise HTTPException(404)
        return deo_json(video_detail(request, movie))

    @app.get("/health")
    async def health():
        return {"ok": True, "movies": database.movie_count()}

    return app


def run_server(host: str = "0.0.0.0", port: int = 8765, db_path: str | None = None) -> None:
    import uvicorn

    from .config import DEFAULT_DB

    database = Database(Path(db_path) if db_path else DEFAULT_DB)
    cfg = load_config()
    app = create_app(database, cfg)
    uvicorn.run(app, host=host, port=port, log_level="info")
