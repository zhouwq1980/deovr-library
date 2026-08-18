from __future__ import annotations

import time
import urllib.error
import urllib.request
from threading import Lock
from urllib.parse import urljoin, urlparse, urlunparse

_cache: dict[str, tuple[str, float]] = {}
# /play 代理：记住某片最近可用的公网 CDN 终链，避免每次 Range/快进都重走 115 网关跳转
_play_upstream: dict[int, tuple[str, float]] = {}
_lock = Lock()
DEFAULT_TTL = 300  # CDN 链接缓存 5 分钟
PLAY_UPSTREAM_TTL = 180  # 播放会话内 CDN 复用约 3 分钟
# STRM 常写 12366；不少 115 设备/代理实际监听 11500
COMMON_115_GATEWAY_PORTS = (11500, 12366)

# 回环地址；局域网私网段会自动识别，无需再配 rewrite_from
DEFAULT_REWRITE_FROM = ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def normalize_rewrite_from(value: object | None) -> list[str]:
    """可选的额外源主机；None/空表示不额外指定（仍会自动改写回环+私网）。"""
    if value is None:
        return []
    items: list[str] = []
    if isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        s = str(value).strip()
        if not s:
            return []
        raw = s.replace(";", ",").split(",")
    for x in raw:
        h = str(x).strip().lower()
        if h:
            items.append(h)
    return items


def _is_loopback_host(host: str) -> bool:
    h = (host or "").lower()
    return h in DEFAULT_REWRITE_FROM or h.endswith(".localhost")


def _is_private_ip(host: str) -> bool:
    """RFC1918 / link-local：STRM 里常见的本机播放网关地址。"""
    h = (host or "").lower().strip("[]")
    parts = h.split(".")
    if len(parts) != 4:
        return False
    try:
        nums = [int(x) for x in parts]
    except ValueError:
        return False
    if any(n < 0 or n > 255 for n in nums):
        return False
    a, b = nums[0], nums[1]
    if a == 10:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    if a == 192 and b == 168:
        return True
    if a == 169 and b == 254:
        return True
    return False


def is_private_or_loopback_host(host: str) -> bool:
    h = (host or "").lower()
    return _is_loopback_host(h) or _is_private_ip(h)


def parse_rewrite_target(lan_host: str) -> tuple[str, int | None]:
    """解析 rewrite_to：支持 IP、host:port、http://host:port。"""
    s = (lan_host or "").strip()
    if not s:
        return "", None
    if "://" in s:
        p = urlparse(s)
        host = (p.hostname or "").strip()
        return host, p.port
    # IPv6 in brackets
    if s.startswith("["):
        p = urlparse(f"http://{s}")
        return (p.hostname or "").strip(), p.port
    if s.count(":") == 1:
        host, _, port_s = s.partition(":")
        host = host.strip()
        try:
            return host, int(port_s.strip())
        except ValueError:
            return s, None
    return s, None


def should_rewrite_host(
    host: str,
    lan_host: str,
    rewrite_from: object | None = None,
) -> bool:
    """默认：回环 + 私网 IP 都改写到 rewrite_to；公网 CDN 不改。"""
    h = (host or "").lower()
    target_host, _ = parse_rewrite_target(lan_host)
    target = (target_host or "").strip().lower()
    if not h or not target or h == target:
        return False
    if _is_loopback_host(h) or _is_private_ip(h):
        return True
    extra = set(normalize_rewrite_from(rewrite_from))
    return h in extra


def rewrite_loopback(
    url: str,
    lan_host: str,
    rewrite_from: object | None = None,
) -> str:
    """把 STRM 里的本机/局域网主机改成 rewrite_to（公网地址不改）。

    rewrite_to 可为 ``192.168.0.40`` 或 ``192.168.0.40:11500``（带端口则覆盖原端口）。
    """
    if not url or not lan_host:
        return url
    p = urlparse(url)
    host = (p.hostname or "").lower()
    target_host, target_port = parse_rewrite_target(lan_host)
    if not target_host:
        return url
    if not should_rewrite_host(host, target_host, rewrite_from=rewrite_from):
        return url
    port = target_port if target_port is not None else p.port
    if port:
        netloc = f"{target_host}:{port}"
    else:
        netloc = target_host
    return urlunparse(p._replace(netloc=netloc))


def replace_url_host_port(url: str, host: str, port: int | None) -> str:
    """只替换 URL 的主机/端口，保留 path/query。"""
    if not url or not host:
        return url
    p = urlparse(url)
    if port:
        netloc = f"{host}:{int(port)}"
    else:
        netloc = host
    return urlunparse(p._replace(netloc=netloc))


def gateway_url_variants(
    url: str,
    lan_host: str,
    rewrite_from: object | None = None,
) -> list[str]:
    """115 网关候选：rewrite_to（含端口）优先，再试常见端口 11500/12366。

    STRM 里常写 ``127.0.0.1:12366``，但设备代理口可能是 ``11500``；
    CDN 过期回退网关时若只打错端口会直接 502。
    """
    if not url or not lan_host:
        return []
    p = urlparse(url)
    raw_host = (p.hostname or "").lower()
    if not should_rewrite_host(raw_host, lan_host, rewrite_from=rewrite_from):
        return []
    target_host, target_port = parse_rewrite_target(lan_host)
    if not target_host:
        return []

    ports: list[int] = []
    if target_port is not None:
        ports.append(int(target_port))
    if p.port:
        ports.append(int(p.port))
    ports.extend(COMMON_115_GATEWAY_PORTS)

    out: list[str] = []
    seen: set[str] = set()
    for port in ports:
        u = replace_url_host_port(url, target_host, port)
        if u and u not in seen and u != url:
            seen.add(u)
            out.append(u)
    return out


def parse_play115(url: str) -> tuple[str, str] | None:
    """从 Emby/Jellyfin ``/play115/{pickcode}/.../[file]`` 取出 pickcode 与文件名。"""
    if not url:
        return None
    p = urlparse(url)
    parts = [x for x in p.path.split("/") if x]
    if len(parts) < 2 or parts[0].lower() != "play115":
        return None
    pickcode = parts[1].strip()
    if not pickcode:
        return None
    last = parts[-1]
    if "." in last and not last.isdigit():
        fname = last
    else:
        fname = f"{pickcode}.mp4"
    return pickcode, fname


def play115_proxy_urls(url: str, bases: list[str]) -> list[str]:
    """把 play115 STRM 转成「115视频代理」``/play/{pickcode}/{file_name}``。

    本机 11500 端口的 uvicorn 服务走这套路径；原 ``/play115/...`` 会 404。
    """
    from urllib.parse import quote

    parsed = parse_play115(url)
    if not parsed:
        return []
    pickcode, fname = parsed
    out: list[str] = []
    seen: set[str] = set()
    for base in bases:
        b = (base or "").strip().rstrip("/")
        if not b:
            continue
        if "://" not in b:
            b = f"http://{b}"
        u = f"{b}/play/{quote(pickcode, safe='')}/{quote(fname, safe='')}"
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def local_115_proxy_bases(lan_host: str = "") -> list[str]:
    """服务端上游优先打本机 115 视频代理，再打 rewrite_to。"""
    bases: list[str] = []
    seen: set[str] = set()

    def add(host: str, port: int) -> None:
        h = (host or "").strip()
        if not h:
            return
        b = f"http://{h}:{int(port)}"
        if b not in seen:
            seen.add(b)
            bases.append(b)

    # 本机 115-Desktop 视频代理（实测监听 *:11500）
    for port in COMMON_115_GATEWAY_PORTS:
        add("127.0.0.1", port)
    host, port = parse_rewrite_target(lan_host)
    if host and not _is_loopback_host(host):
        if port is not None:
            add(host, port)
        for p in COMMON_115_GATEWAY_PORTS:
            add(host, p)
    elif host and port is not None:
        add(host, port)
    return bases


def _follow_once(url: str, timeout: float = 10.0) -> tuple[str, int | None]:
    req = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": "DeoVR-Library/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.geturl(), getattr(resp, "status", 200)
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location")
        if e.code in (301, 302, 303, 307, 308) and loc:
            return urljoin(url, loc), e.code
        raise


def is_public_https_url(url: str) -> bool:
    """公网 https（CDN 直链），非本机/私网网关。"""
    try:
        p = urlparse(url or "")
    except Exception:
        return False
    if (p.scheme or "").lower() != "https":
        return False
    host = (p.hostname or "").lower()
    return bool(host) and not is_private_or_loopback_host(host)


def get_play_upstream(movie_id: int) -> str:
    """取出 /play 会话缓存的公网上游（未命中或过期返回空）。"""
    now = time.time()
    with _lock:
        hit = _play_upstream.get(int(movie_id))
        if hit and hit[1] > now and is_public_https_url(hit[0]):
            return hit[0]
        if hit:
            _play_upstream.pop(int(movie_id), None)
    return ""


def set_play_upstream(movie_id: int, url: str, ttl: int = PLAY_UPSTREAM_TTL) -> None:
    """缓存 /play 跟跳后的公网 CDN，供后续 Range 直打，减轻快进卡顿。"""
    if not is_public_https_url(url):
        return
    with _lock:
        _play_upstream[int(movie_id)] = (url, time.time() + max(30, ttl))


def clear_play_upstream(movie_id: int) -> None:
    with _lock:
        _play_upstream.pop(int(movie_id), None)


def resolve_media_url(
    url: str,
    *,
    lan_host: str = "",
    rewrite_from: object | None = None,
    ttl: int = DEFAULT_TTL,
    use_cache: bool = True,
) -> str:
    """
    服务端跟随 STRM 跳转，尽量拿到最终可播地址（如 115 CDN https）。
    避免头显跟随到 127.0.0.1 / 旧局域网 IP。
    """
    if not url:
        return url

    # 缓存键含改写目标，避免换 IP 后仍命中旧结果
    from_key = ",".join(normalize_rewrite_from(rewrite_from)) if rewrite_from else "auto"
    cache_key = f"{url}|{lan_host}|{from_key}"
    now = time.time()
    if use_cache:
        with _lock:
            hit = _cache.get(cache_key)
            if hit and hit[1] > now:
                return hit[0]

    current = url
    final = url
    reached_public = False
    try:
        for _ in range(6):
            # 本机解析时用 127.0.0.1 更稳；中间跳转若仍是 loopback 保持本机访问
            try:
                nxt, code = _follow_once(current)
            except Exception:
                # HEAD 失败时试 GET（只读头）
                req = urllib.request.Request(
                    current,
                    headers={"User-Agent": "DeoVR-Library/1.0", "Range": "bytes=0-0"},
                )
                try:
                    with urllib.request.urlopen(req, timeout=12) as resp:
                        nxt = resp.geturl()
                        code = getattr(resp, "status", 200)
                except urllib.error.HTTPError as e:
                    loc = e.headers.get("Location")
                    if e.code in (301, 302, 303, 307, 308) and loc:
                        nxt, code = urljoin(current, loc), e.code
                    else:
                        break
                except Exception:
                    break

            final = nxt
            host = (urlparse(nxt).hostname or "").lower()
            if is_public_https_url(nxt):
                reached_public = True
            if code and code < 300:
                break
            if host not in ("127.0.0.1", "localhost", "::1") and urlparse(nxt).scheme == "https":
                # 再跟一次看是否还有跳转
                current = nxt
                try:
                    nxt2, code2 = _follow_once(current)
                    final = nxt2
                    if is_public_https_url(nxt2):
                        reached_public = True
                    if code2 and code2 < 300:
                        break
                    if nxt2 == current:
                        break
                    current = nxt2
                    continue
                except Exception:
                    break
            if nxt == current:
                break
            current = nxt
    except Exception:
        final = url

    # 仅当仍落在私网/回环时才改写到局域网 IP；已到 CDN 不要改
    if lan_host and not is_public_https_url(final):
        final = rewrite_loopback(final, lan_host, rewrite_from=rewrite_from)

    # 未解析到公网 CDN 时不缓存，避免网关短暂 502 后长期命中坏链
    if use_cache and final and reached_public:
        with _lock:
            _cache[cache_key] = (final, now + max(30, ttl))
    return final
