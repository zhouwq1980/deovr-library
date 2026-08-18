from __future__ import annotations

import socket
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
import json as _json
from starlette.middleware.base import BaseHTTPMiddleware

from .config import DEFAULT_CONFIG, load_config, save_config
from .db import Database
from .media import (
    clear_play_upstream,
    get_play_upstream,
    is_private_or_loopback_host,
    is_public_https_url,
    normalize_rewrite_from,
    parse_rewrite_target,
    resolve_media_url,
    rewrite_loopback,
    set_play_upstream,
)
from .nfo import is_http_url, media_content_type, read_strm
from .players import (
    launch_local_player,
    merge_external_players,
    players_for_movie,
    scheme_href,
)
from .projection import hint_from_movie
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
            # rewrite_to 可能是 115 网关 host:port，片库根地址只用主机名 + 本服务端口
            host_only, _ = parse_rewrite_target(lan) if lan else ("", None)
            if host_only:
                return f"{proto}://{host_only}:{port}"

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
        # 投影按单片文件名/NFO 推断，不按目录 2D/VR 划分（混目录友好）
        hint = hint_from_movie(movie)
        is_vr = hint.kind == "vr" or hint.screen_type in (
            "dome",
            "sphere",
            "fisheye",
            "mkx200",
            "mkx220",
            "rf52",
            "fisheye190",
            "vrca220",
        )
        runtime_min = movie.get("runtime") or 0
        video_length = int(runtime_min) * 60 if runtime_min else 0
        mid = movie["id"]
        bu = base_url(request)
        thumb = f"{bu}/cover/{mid}.jpg?v={thumb_cache_token(movie.get('poster_path'), mid)}"
        play_proxy = f"{bu}/play/{mid}"
        direct = media_url_for_client(request, movie) or play_proxy
        # DeoVR 对过期/防盗链 CDN 直链常失败；默认给本服务 /play（可代理或现解析后跳转）
        if cfg_l.get("deovr_use_play_url", True):
            play = play_proxy
        else:
            play = direct
        res = int(cfg_l.get("default_resolution") or (2160 if is_vr else 1080))
        height = res
        width = res * 2 if is_vr else max(1, int(round(res * 16 / 9)))
        screen_hint = hint.screen_type
        stereo_hint = hint.stereo_mode
        if cfg_l.get("deovr_lock_projection"):
            if not screen_hint:
                screen_hint = (
                    (cfg_l.get("vr_screen_type") if is_vr else cfg_l.get("flat_screen_type"))
                    or ("dome" if is_vr else "flat")
                )
            if not stereo_hint:
                stereo_hint = (
                    (cfg_l.get("vr_stereo_mode") if is_vr else cfg_l.get("flat_stereo_mode"))
                    or ("sbs" if is_vr else "off")
                )
        detail: dict[str, Any] = {
            "id": mid,
            "title": movie.get("title") or movie.get("code") or f"#{mid}",
            "authorized": 1,
            "description": movie.get("plot") or "",
            # 官方文档：is3d 需为 true；具体 2D/3D 由 stereoMode/screenType 或播放器内调节决定
            "is3d": True,
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
                            "resolution": height,
                            "height": height,
                            "width": width,
                            "url": play,
                        }
                    ],
                }
            ],
        }
        # 有文件名线索才写 screenType；stereoMode 默认留空以便头显内改 2D/3D
        # 锁定模式才把 stereo 一并写入
        if cfg_l.get("deovr_lock_projection"):
            detail["screenType"] = screen_hint or "flat"
            detail["stereoMode"] = stereo_hint or "off"
        else:
            detail["screenType"] = screen_hint or ""
            detail["stereoMode"] = ""
        return detail

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
        region: str | None = None,
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
        hide = bool(cfg_l.get("hide_strm_without_nfo_poster"))

        if genre:
            items = database.search_movies(
                genre=genre,
                page=1,
                page_size=limit,
                hide_strm_without_nfo_poster=hide,
            )["items"]
            return deovr_scene_from_movies(request, genre, items)

        if actor:
            items = database.search_movies(
                actor=actor,
                page=1,
                page_size=limit,
                hide_strm_without_nfo_poster=hide,
            )["items"]
            return deovr_scene_from_movies(request, actor, items)

        if studio:
            items = database.search_movies(
                studio=studio,
                page=1,
                page_size=limit,
                hide_strm_without_nfo_poster=hide,
            )["items"]
            return deovr_scene_from_movies(request, studio, items)

        if kind:
            items = database.list_for_deovr(
                kind=kind, limit=limit, hide_strm_without_nfo_poster=hide
            )
            label = {"2d": "2D", "vr": "VR"}.get(kind, kind.upper())
            return deovr_scene_from_movies(request, label, items)

        if region:
            items = database.list_for_deovr(
                region=region, limit=limit, hide_strm_without_nfo_poster=hide
            )
            label = {"jp": "日本", "western": "欧美"}.get(region, region)
            return deovr_scene_from_movies(request, label, items)

        if library_id:
            lib_name = next(
                (x["name"] for x in database.list_libraries() if x["id"] == library_id),
                f"Lib {library_id}",
            )
            items = database.list_for_deovr(
                library_id=library_id, limit=limit, hide_strm_without_nfo_poster=hide
            )
            return deovr_scene_from_movies(request, lib_name, items)

        scenes: list[dict[str, Any]] = []

        recent = database.list_for_deovr(
            limit=min(100, limit), hide_strm_without_nfo_poster=hide
        )
        scenes.append(
            {"name": "Recent", "list": [deovr_list_item(request, m) for m in recent]}
        )

        for lib in database.list_libraries():
            items = database.list_for_deovr(
                library_id=lib["id"],
                limit=min(120, limit),
                hide_strm_without_nfo_poster=hide,
            )
            if items:
                scenes.append(
                    {
                        "name": lib["name"][:24],
                        "list": [deovr_list_item(request, m) for m in items],
                    }
                )

        for k, label in (("2d", "2D"), ("vr", "VR")):
            items = database.list_for_deovr(
                kind=k, limit=min(100, limit), hide_strm_without_nfo_poster=hide
            )
            if items:
                scenes.append(
                    {"name": label, "list": [deovr_list_item(request, m) for m in items]}
                )

        for r, label in (("jp", "日本"), ("western", "欧美")):
            items = database.list_for_deovr(
                region=r, limit=min(100, limit), hide_strm_without_nfo_poster=hide
            )
            if items:
                scenes.append(
                    {"name": label, "list": [deovr_list_item(request, m) for m in items]}
                )

        # 热门类型：每个类型一个底栏 Tab（直接出片，禁止文件夹套娃）
        for g in database.facet_genres(genre_tabs):
            gname = g["name"]
            items = database.search_movies(
                genre=gname,
                page=1,
                page_size=min(80, limit),
                hide_strm_without_nfo_poster=hide,
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
                    actor=aname,
                    page=1,
                    page_size=min(60, limit),
                    hide_strm_without_nfo_poster=hide,
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
        for key in ("q", "kind", "region", "library_id", "sort", "actor", "genre", "studio"):
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

    @app.get("/region/{name}", response_class=HTMLResponse)
    async def browse_region(name: str):
        r = name.lower().strip()
        if r in ("japan", "日", "日本"):
            r = "jp"
        elif r in ("west", "western", "欧美", "歐美"):
            r = "western"
        if r not in ("jp", "western"):
            raise HTTPException(404)
        return RedirectResponse(url=f"/browse?region={r}", status_code=302)

    @app.get("/m/{movie_id}", response_class=HTMLResponse)
    async def movie_page(request: Request, movie_id: int):
        movie = database.get_movie(movie_id)
        if not movie:
            raise HTTPException(404, "未找到影片")
        try:
            cfg_l = load_config()
            app.state.cfg = cfg_l
        except Exception:
            cfg_l = app.state.cfg
        movie = dict(movie)
        movie["cover_token"] = thumb_cache_token(movie.get("poster_path"), movie_id)
        raw = strm_raw_url(movie)
        play = media_url_for_client(request, movie) or f"{base_url(request)}/play/{movie_id}"
        # 外接播放器用本服务 /play（局域网可达、可代理）
        ext_url = f"{base_url(request)}/play/{movie_id}"
        return _render(
            "detail.html",
            movie=movie,
            base=base_url(request),
            play_url=play,
            raw_url=raw,
            play_changed=bool(raw and play and raw != play),
            external_players=players_for_movie(cfg_l, ext_url),
            ext_play_url=ext_url,
        )

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        try:
            cfg_l = load_config()
            app.state.cfg = cfg_l
        except Exception:
            cfg_l = app.state.cfg
        detected = _detect_lan_ip()
        return _render(
            "settings.html",
            base=base_url(request),
            players=merge_external_players(cfg_l.get("external_players")),
            saved=request.query_params.get("saved") == "1",
            rewrite_enabled=bool(cfg_l.get("rewrite_localhost_enabled", True)),
            rewrite_to=str(cfg_l.get("rewrite_to") or cfg_l.get("lan_host") or ""),
            auto_resolve=bool(cfg_l.get("auto_resolve_private_strm", True)),
            resolve_cdn=bool(cfg_l.get("resolve_strm_redirects", False)),
            proxy_strm=bool(cfg_l.get("proxy_strm", True)),
            use_play_url=bool(cfg_l.get("deovr_use_play_url", True)),
            detected_ip=detected or "",
        )

    @app.get("/api/settings")
    async def api_get_settings():
        try:
            cfg_l = load_config()
            app.state.cfg = cfg_l
        except Exception:
            cfg_l = app.state.cfg
        detected = _detect_lan_ip()
        return {
            "rewrite_localhost_enabled": bool(cfg_l.get("rewrite_localhost_enabled", True)),
            "rewrite_to": str(cfg_l.get("rewrite_to") or cfg_l.get("lan_host") or ""),
            "auto_resolve_private_strm": bool(cfg_l.get("auto_resolve_private_strm", True)),
            "resolve_strm_redirects": bool(cfg_l.get("resolve_strm_redirects", False)),
            "proxy_strm": bool(cfg_l.get("proxy_strm", True)),
            "deovr_use_play_url": bool(cfg_l.get("deovr_use_play_url", True)),
            "detected_ip": detected or "",
        }

    @app.get("/api/settings/detect-ip")
    async def api_detect_ip():
        ip = _detect_lan_ip() or ""
        return {"ip": ip, "suggest": f"{ip}:12366" if ip else ""}

    @app.post("/api/settings/media")
    async def api_save_media_settings(request: Request):
        """保存 115 网关 / STRM 改写与播放相关设置。"""
        try:
            body = await request.json()
        except Exception as e:
            raise HTTPException(400, f"无效 JSON: {e}") from e
        if not isinstance(body, dict):
            raise HTTPException(400, "需要 JSON 对象")
        try:
            cfg_l = load_config()
        except Exception:
            cfg_l = dict(app.state.cfg)

        if "rewrite_localhost_enabled" in body:
            cfg_l["rewrite_localhost_enabled"] = bool(body.get("rewrite_localhost_enabled"))
        if "rewrite_to" in body:
            rw = str(body.get("rewrite_to") or "").strip()
            # 去掉误填的 http://
            if "://" in rw:
                host, port = parse_rewrite_target(rw)
                rw = f"{host}:{port}" if host and port else (host or rw)
            cfg_l["rewrite_to"] = rw
        if "auto_resolve_private_strm" in body:
            cfg_l["auto_resolve_private_strm"] = bool(body.get("auto_resolve_private_strm"))
        if "resolve_strm_redirects" in body:
            cfg_l["resolve_strm_redirects"] = bool(body.get("resolve_strm_redirects"))
        if "proxy_strm" in body:
            cfg_l["proxy_strm"] = bool(body.get("proxy_strm"))
        if "deovr_use_play_url" in body:
            cfg_l["deovr_use_play_url"] = bool(body.get("deovr_use_play_url"))

        save_config(cfg_l, DEFAULT_CONFIG)
        app.state.cfg = cfg_l
        return {
            "ok": True,
            "rewrite_localhost_enabled": bool(cfg_l.get("rewrite_localhost_enabled", True)),
            "rewrite_to": str(cfg_l.get("rewrite_to") or ""),
            "auto_resolve_private_strm": bool(cfg_l.get("auto_resolve_private_strm", True)),
            "resolve_strm_redirects": bool(cfg_l.get("resolve_strm_redirects", False)),
            "proxy_strm": bool(cfg_l.get("proxy_strm", True)),
            "deovr_use_play_url": bool(cfg_l.get("deovr_use_play_url", True)),
        }

    @app.post("/api/settings/players")
    async def api_save_players(request: Request):
        """保存外接播放器：JSON { players: [...] }。"""
        try:
            body = await request.json()
        except Exception as e:
            raise HTTPException(400, f"无效 JSON: {e}") from e
        players = merge_external_players(body.get("players") if isinstance(body, dict) else body)
        try:
            cfg_l = load_config()
        except Exception:
            cfg_l = dict(app.state.cfg)
        cfg_l["external_players"] = players
        save_config(cfg_l, DEFAULT_CONFIG)
        app.state.cfg = cfg_l
        return {"ok": True, "players": players}

    @app.get("/api/launch-player/{movie_id}/{player_id}")
    async def api_launch_player(request: Request, movie_id: int, player_id: str):
        """在运行本服务的电脑上用 path 启动播放器。"""
        movie = database.get_movie(movie_id)
        if not movie:
            raise HTTPException(404, "未找到影片")
        try:
            cfg_l = load_config()
            app.state.cfg = cfg_l
        except Exception:
            cfg_l = app.state.cfg
        players = {p["id"]: p for p in merge_external_players(cfg_l.get("external_players"))}
        player = players.get(player_id)
        if not player or not player.get("enabled"):
            raise HTTPException(404, "播放器未启用或不存在")
        media_url = f"{base_url(request)}/play/{movie_id}"
        try:
            msg = launch_local_player(player, media_url)
        except Exception as e:
            raise HTTPException(400, str(e)) from e
        # 浏览器点链接时给简单提示页
        accept = (request.headers.get("accept") or "").lower()
        if "text/html" in accept:
            return HTMLResponse(
                f"<html><body style='font-family:sans-serif;padding:2rem'>"
                f"<p>{msg}</p><p><code>{media_url}</code></p>"
                f"<p><a href='/m/{movie_id}'>返回详情</a></p></body></html>"
            )
        return {"ok": True, "message": msg, "url": media_url}

    @app.get("/open-player/{movie_id}/{player_id}")
    async def open_player_scheme(request: Request, movie_id: int, player_id: str):
        """302 跳到播放器 URL scheme（在浏览器用的电脑上唤起）。"""
        movie = database.get_movie(movie_id)
        if not movie:
            raise HTTPException(404, "未找到影片")
        try:
            cfg_l = load_config()
            app.state.cfg = cfg_l
        except Exception:
            cfg_l = app.state.cfg
        players = {p["id"]: p for p in merge_external_players(cfg_l.get("external_players"))}
        player = players.get(player_id)
        if not player or not player.get("enabled"):
            raise HTTPException(404, "播放器未启用或不存在")
        media_url = f"{base_url(request)}/play/{movie_id}"
        href = scheme_href(player, media_url)
        if not href:
            raise HTTPException(400, "该播放器未配置 scheme，请用「本机启动」或到 /settings 填写")
        return RedirectResponse(url=href, status_code=302)

    @app.get("/api/movies")
    async def api_movies(
        q: str = "",
        actor: str = "",
        genre: str = "",
        studio: str = "",
        kind: str = "",
        region: str = "",
        library_id: int | None = None,
        year: int | None = None,
        sort: str = "updated",
        page: int = Query(1, ge=1),
        page_size: int = Query(48, ge=1, le=200),
    ):
        try:
            cfg_l = load_config()
            app.state.cfg = cfg_l
        except Exception:
            cfg_l = app.state.cfg
        data = database.search_movies(
            q=q,
            actor=actor,
            genre=genre,
            studio=studio,
            kind=kind,
            region=region,
            library_id=library_id,
            year=year,
            sort=sort,
            page=page,
            page_size=page_size,
            hide_strm_without_nfo_poster=bool(
                cfg_l.get("hide_strm_without_nfo_poster")
            ),
        )
        for item in data.get("items") or []:
            item["cover_token"] = thumb_cache_token(item.get("poster_path"), int(item["id"]))
        return data

    @app.get("/api/facets")
    async def api_facets(
        q: str = "",
        kind: str = "",
        region: str = "",
        library_id: int | None = None,
        actor: str = "",
        genre: str = "",
        studio: str = "",
    ):
        try:
            cfg_l = load_config()
            app.state.cfg = cfg_l
        except Exception:
            cfg_l = app.state.cfg
        hide = bool(cfg_l.get("hide_strm_without_nfo_poster"))
        # 级联：片商/类型/演员随 kind·region·其它筛选缩小选项与数量
        common = dict(
            q=q,
            kind=kind,
            region=region,
            library_id=library_id,
            hide_strm_without_nfo_poster=hide,
        )
        return {
            "actors": database.facet_actors(
                300, **common, genre=genre, studio=studio
            ),
            "genres": database.facet_genres(
                300, **common, actor=actor, studio=studio
            ),
            "studios": database.facet_studios(
                200, **common, actor=actor, genre=genre
            ),
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

        # 给浏览器/远程的「直链」：解析到公网 CDN（不要把 127.0.0.1 甩给外网）
        client_url = media_url_for_client(request, movie)
        if not client_url or not is_http_url(client_url):
            raise HTTPException(404, "无有效播放地址（STRM 为空或本地文件缺失）")

        force_redirect = (request.query_params.get("redirect") or "").lower() in (
            "1",
            "true",
            "yes",
        )
        if force_redirect or not cfg_l.get("proxy_strm", True):
            return RedirectResponse(url=client_url, status_code=302)

        try:
            import httpx
        except ImportError:
            return RedirectResponse(url=client_url, status_code=302)

        # 代理上游（快进 = 新 Range 请求）：
        # - 优先复用已解析/会话缓存的公网 CDN（轻量 UA），避免每次都走 115 网关跳转
        # - CDN 403/失败再回退 LAN 网关 → 本机 127.0.0.1 网关
        # - Chrome UA 直打 CDN 常 403；网关用浏览器 UA，CDN 用轻量 UA
        raw_host = (urlparse(raw).hostname or "").lower()
        light_ua = "DeoVR-Library/1.0"
        browser_ua = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        upstream_headers = {
            "Accept": "*/*",
        }
        range_h = request.headers.get("range") or request.headers.get("Range")
        if range_h:
            upstream_headers["Range"] = range_h

        async def _open_upstream(fetch_url: str, headers: dict[str, str]):
            # 连接超时缩短：死掉的 127.0.0.1 不要拖死每一次快进
            client = httpx.AsyncClient(
                follow_redirects=True,
                timeout=httpx.Timeout(60.0, connect=3.0),
                trust_env=False,
            )
            try:
                upstream = await client.send(
                    client.build_request(
                        request.method if request.method in ("GET", "HEAD") else "GET",
                        fetch_url,
                        headers=headers,
                    ),
                    stream=True,
                )
                return client, upstream
            except Exception:
                await client.aclose()
                raise

        def _cdn_url() -> str:
            cached = get_play_upstream(movie_id)
            if cached:
                return cached
            for cand in (client_url,):
                if is_public_https_url(cand):
                    return cand
            try:
                resolved = resolve_media_url(
                    raw,
                    lan_host="",
                    ttl=int(cfg_l.get("media_url_cache_ttl") or 300),
                )
            except Exception:
                resolved = ""
            if is_public_https_url(resolved):
                return resolved
            return ""

        def _lan_gateway_url() -> str:
            """rewrite_to 上的同路径网关（115 跑在另一台局域网机器）。"""
            target = rewrite_target(request)
            if not target or not is_private_or_loopback_host(raw_host):
                return ""
            alt = rewrite_loopback(raw, target, rewrite_from=cfg_l.get("rewrite_from"))
            if alt and alt != raw and is_http_url(alt):
                return alt
            return ""

        # 候选顺序：CDN → LAN 网关 → 本机网关（公网 STRM 只打 client_url）
        candidates: list[tuple[str, str]] = []
        seen: set[str] = set()

        def _add(url: str, ua: str) -> None:
            u = (url or "").strip()
            if not u or u in seen:
                return
            seen.add(u)
            candidates.append((u, ua))

        if is_private_or_loopback_host(raw_host):
            _add(_cdn_url(), light_ua)
            _add(_lan_gateway_url(), browser_ua)
            _add(raw, browser_ua)
        else:
            _add(client_url if is_http_url(client_url) else raw, light_ua)

        if not candidates:
            raise HTTPException(502, "无可用上游播放地址")

        gateway_err: Exception | None = None
        client = upstream = None  # type: ignore
        last_status = 0
        used_fetch = ""
        for fetch_url, ua in candidates:
            headers = {**upstream_headers, "User-Agent": ua}
            try:
                client, upstream = await _open_upstream(fetch_url, headers)
            except Exception as e:
                gateway_err = e
                client = upstream = None
                if is_public_https_url(fetch_url):
                    clear_play_upstream(movie_id)
                continue
            if upstream.status_code < 400:
                gateway_err = None
                used_fetch = fetch_url
                break
            last_status = upstream.status_code
            gateway_err = Exception(f"HTTP {upstream.status_code} from {fetch_url[:80]}")
            if is_public_https_url(fetch_url) or upstream.status_code in (401, 403, 404):
                clear_play_upstream(movie_id)
            try:
                await upstream.aread()
            except Exception:
                pass
            await upstream.aclose()
            await client.aclose()
            client = upstream = None

        if upstream is None or client is None:
            port = urlparse(raw).port or 80
            if is_private_or_loopback_host(raw_host):
                raise HTTPException(
                    502,
                    f"无法连接 115 播放网关/CDN（Connection refused / HTTP {last_status or 'n/a'}）。"
                    f"STRM={raw_host}:{port}。请确认网关已启动，或在设置里改 rewrite_to。"
                    + (f" 详情: {gateway_err}" if gateway_err else ""),
                )
            raise HTTPException(502, f"上游媒体不可用: {gateway_err}")

        if upstream.status_code >= 400:
            body = await upstream.aread()
            await upstream.aclose()
            await client.aclose()
            clear_play_upstream(movie_id)
            raise HTTPException(
                upstream.status_code, body.decode("utf-8", errors="ignore")[:200]
            )

        # 记住跟跳后的公网终链，后续 Range/快进直打 CDN
        try:
            final_u = str(upstream.url)
        except Exception:
            final_u = used_fetch
        if is_public_https_url(final_u):
            set_play_upstream(movie_id, final_u)

        out_headers: dict[str, str] = {
            "Access-Control-Allow-Origin": "*",
            "Accept-Ranges": "bytes",
            # 禁止中间层把整段视频缓存成不可 Range 的实体
            "Cache-Control": "no-store",
        }
        ctype = upstream.headers.get("content-type") or "application/octet-stream"
        out_headers["Content-Type"] = ctype
        for src, dest in (
            ("content-length", "Content-Length"),
            ("content-range", "Content-Range"),
            ("accept-ranges", "Accept-Ranges"),
        ):
            val = upstream.headers.get(src)
            if val:
                out_headers[dest] = val

        if request.method == "HEAD":
            await upstream.aclose()
            await client.aclose()
            return Response(status_code=upstream.status_code, headers=out_headers)

        async def body_iter():
            try:
                async for chunk in upstream.aiter_bytes(chunk_size=64 * 1024):
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()

        return StreamingResponse(
            body_iter(),
            status_code=upstream.status_code,
            headers=out_headers,
            media_type=out_headers.get("Content-Type"),
        )

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

    @app.api_route("/deovr/region/{region}", methods=["GET", "POST", "HEAD", "OPTIONS"])
    async def deovr_by_region(request: Request, region: str):
        r = region.lower().strip()
        if r in ("japan", "日", "日本"):
            r = "jp"
        elif r in ("west", "western", "欧美", "歐美"):
            r = "western"
        if r not in ("jp", "western"):
            raise HTTPException(404, "region 仅为 jp 或 western")
        return deo_json(build_deovr_library(request, region=r))

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
