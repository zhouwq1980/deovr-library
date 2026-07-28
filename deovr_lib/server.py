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
from .media import resolve_media_url, rewrite_loopback
from .nfo import is_http_url, media_content_type, read_strm
from .thumbs import ensure_thumb

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
        proto = request.headers.get("x-forwarded-proto") or request.url.scheme
        host = request.headers.get("host") or f"{request.url.hostname}:{request.url.port}"
        return f"{proto}://{host}"

    def rewrite_target(request: Request) -> str:
        """自定义改地址目标 IP（rewrite_to）；未填则用请求 Host / 自动检测。"""
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
        if name and name not in ("127.0.0.1", "localhost", "::1"):
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
                # 本地视频：用本服务 /play 直出，不走外链
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
        # 本地文件：返回本服务播放地址
        if is_local_media(movie):
            return f"{base_url(request)}/play/{movie['id']}"

        raw = strm_raw_url(movie)
        if not raw:
            return ""
        try:
            cfg_l = load_config()
            app.state.cfg = cfg_l
        except Exception:
            cfg_l = app.state.cfg
        target = rewrite_target(request)
        url = raw
        if cfg_l.get("resolve_strm_redirects", False):
            url = resolve_media_url(
                raw,
                lan_host=target,
                ttl=int(cfg_l.get("media_url_cache_ttl") or 300),
            )
        if cfg_l.get("rewrite_localhost_enabled", True) and target:
            url = rewrite_loopback(url, target)
        return url

    def video_detail(request: Request, movie: dict[str, Any]) -> dict[str, Any]:
        cfg_l = app.state.cfg
        is_vr = movie.get("kind") == "vr"
        runtime_min = movie.get("runtime") or 0
        video_length = int(runtime_min) * 60 if runtime_min else 0
        mid = movie["id"]
        bu = base_url(request)
        screen = cfg_l["vr_screen_type"] if is_vr else cfg_l["flat_screen_type"]
        stereo = cfg_l["vr_stereo_mode"] if is_vr else cfg_l["flat_stereo_mode"]
        thumb = f"{bu}/cover/{mid}.jpg"
        play = f"{bu}/play/{mid}"
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
                {"tag": {"id": i + 1, "name": n}}
                for i, n in enumerate(movie.get("genres") or [])
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
        ua = (request.headers.get("user-agent") or "").lower()
        accept = (request.headers.get("accept") or "").lower()
        if "deovr" in ua or "deo vr" in ua:
            return True
        # 明确只要 JSON、不要 HTML 时（DeoVR / curl）
        if "application/json" in accept and "text/html" not in accept:
            return True
        return False

    def build_deovr_library(
        request: Request,
        *,
        kind: str | None = None,
        genre: str | None = None,
        library_id: int | None = None,
    ) -> dict[str, Any]:
        """DeoVR Selection Scene JSON。可按 kind/genre/library 收窄，避免点分区异常。"""
        cfg_l = load_config()
        app.state.cfg = cfg_l
        limit = int(cfg_l.get("deovr_section_limit") or 200)
        scenes: list[dict[str, Any]] = []

        # 单过滤器模式：只返回一个分区（给独立入口用）
        if genre:
            items = database.search_movies(genre=genre, page=1, page_size=limit)["items"]
            scenes.append(
                {
                    "name": genre,
                    "list": [deovr_list_item(request, m) for m in items],
                }
            )
            return {"authorized": "1", "scenes": scenes}

        if kind:
            items = database.list_for_deovr(kind=kind, limit=limit)
            scenes.append(
                {
                    "name": kind.upper(),
                    "list": [deovr_list_item(request, m) for m in items],
                }
            )
            return {"authorized": "1", "scenes": scenes}

        if library_id:
            lib_name = next(
                (x["name"] for x in database.list_libraries() if x["id"] == library_id),
                f"Lib {library_id}",
            )
            items = database.list_for_deovr(library_id=library_id, limit=limit)
            scenes.append(
                {
                    "name": lib_name,
                    "list": [deovr_list_item(request, m) for m in items],
                }
            )
            return {"authorized": "1", "scenes": scenes}

        # 完整库：分区宜少、宜短，否则 DeoVR 切 Tab 容易异常退回
        recent = database.list_for_deovr(limit=min(80, limit))
        scenes.append(
            {"name": "最近更新", "list": [deovr_list_item(request, m) for m in recent]}
        )

        for lib in database.list_libraries():
            items = database.list_for_deovr(library_id=lib["id"], limit=min(120, limit))
            scenes.append(
                {"name": lib["name"], "list": [deovr_list_item(request, m) for m in items]}
            )

        # 2D / VR 各一页（独立精简列表，避免与目录重复过大）
        for k, label in (("2d", "2D"), ("vr", "VR")):
            items = database.list_for_deovr(kind=k, limit=min(100, limit))
            if items:
                scenes.append(
                    {"name": label, "list": [deovr_list_item(request, m) for m in items]}
                )

        # 热门类型（DeoVR 底栏可点的「类型」Tab）
        for g in database.facet_genres(12):
            gname = g["name"]
            items = database.search_movies(genre=gname, page=1, page_size=min(60, limit))["items"]
            if items:
                scenes.append(
                    {
                        "name": gname[:20],
                        "list": [deovr_list_item(request, m) for m in items],
                    }
                )

        return {"authorized": "1", "scenes": scenes}

    @app.api_route("/", methods=["GET", "POST", "HEAD", "OPTIONS"])
    async def index(request: Request):
        # DeoVR 常 POST/带专用 UA 访问根路径；若返回网页会表现为「点什么都像回首页」
        if request.method in ("POST", "OPTIONS"):
            return JSONResponse(build_deovr_library(request))
        if wants_deovr_json(request):
            return JSONResponse(build_deovr_library(request))
        return render_index()

    @app.get("/browse", response_class=HTMLResponse)
    async def browse_home(request: Request):
        return render_index()

    @app.get("/genre/{name:path}", response_class=HTMLResponse)
    async def browse_genre(name: str):
        return render_index({"genre": unquote(name)})

    @app.get("/actor/{name:path}", response_class=HTMLResponse)
    async def browse_actor(name: str):
        return render_index({"actor": unquote(name)})

    @app.get("/kind/{name}", response_class=HTMLResponse)
    async def browse_kind(name: str):
        k = name.lower().strip()
        if k not in ("2d", "vr"):
            raise HTTPException(404)
        return render_index({"kind": k})

    @app.get("/m/{movie_id}", response_class=HTMLResponse)
    async def movie_page(request: Request, movie_id: int):
        movie = database.get_movie(movie_id)
        if not movie:
            raise HTTPException(404, "未找到影片")
        return _render("detail.html", movie=movie, base=base_url(request))

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
        return database.search_movies(
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
            path = str(thumb)
        return FileResponse(
            path,
            media_type="image/jpeg",
            headers={
                "Cache-Control": "public, max-age=86400",
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
        target = rewrite_target(request)
        url = raw
        if cfg_l.get("resolve_strm_redirects", False):
            url = resolve_media_url(
                url,
                lan_host=target,
                ttl=int(cfg_l.get("media_url_cache_ttl") or 300),
            )
        if cfg_l.get("rewrite_localhost_enabled", True) and target:
            url = rewrite_loopback(url, target)
        return RedirectResponse(url=url, status_code=302)

    @app.get("/api/resolve/{movie_id}")
    async def api_resolve(request: Request, movie_id: int):
        movie = database.get_movie(movie_id)
        if not movie:
            raise HTTPException(404)
        raw = strm_raw_url(movie)
        final = media_url_for_client(request, movie)
        return {
            "raw": raw,
            "final": final,
            "rewrite_enabled": bool(app.state.cfg.get("rewrite_localhost_enabled", True)),
            "rewrite_to": rewrite_target(request),
            "resolve_strm_redirects": bool(app.state.cfg.get("resolve_strm_redirects", False)),
        }

    @app.api_route("/deovr", methods=["GET", "POST", "HEAD", "OPTIONS"])
    @app.api_route("/deovr/", methods=["GET", "POST", "HEAD", "OPTIONS"])
    @app.api_route("/deovr.json", methods=["GET", "POST", "HEAD", "OPTIONS"])
    async def deovr_library(request: Request):
        return JSONResponse(build_deovr_library(request))

    @app.api_route("/deovr/kind/{kind}", methods=["GET", "POST", "HEAD", "OPTIONS"])
    async def deovr_by_kind(request: Request, kind: str):
        k = kind.lower().strip()
        if k not in ("2d", "vr"):
            raise HTTPException(404, "kind 仅为 2d 或 vr")
        return JSONResponse(build_deovr_library(request, kind=k))

    @app.api_route("/deovr/genre/{name:path}", methods=["GET", "POST", "HEAD", "OPTIONS"])
    async def deovr_by_genre(request: Request, name: str):
        return JSONResponse(build_deovr_library(request, genre=unquote(name)))

    @app.api_route("/deovr/{movie_id}", methods=["GET", "POST", "OPTIONS"])
    async def deovr_video(request: Request, movie_id: int):
        movie = database.get_movie(movie_id)
        if not movie:
            raise HTTPException(404)
        return JSONResponse(
            video_detail(request, movie),
            headers={"Cache-Control": "no-store"},
        )

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
