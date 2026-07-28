from __future__ import annotations

import time
import urllib.error
import urllib.request
from threading import Lock
from urllib.parse import urljoin, urlparse, urlunparse

_cache: dict[str, tuple[str, float]] = {}
_lock = Lock()
DEFAULT_TTL = 300  # CDN 链接缓存 5 分钟


def rewrite_loopback(url: str, lan_host: str) -> str:
    """把 127.0.0.1/localhost 换成局域网 IP，供头显访问本机播放服务。"""
    if not url or not lan_host:
        return url
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if host in ("127.0.0.1", "localhost", "::1"):
        netloc = lan_host
        if p.port:
            netloc = f"{lan_host}:{p.port}"
        return urlunparse(p._replace(netloc=netloc))
    return url


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


def resolve_media_url(
    url: str,
    *,
    lan_host: str = "",
    ttl: int = DEFAULT_TTL,
    use_cache: bool = True,
) -> str:
    """
    服务端跟随 STRM 跳转，尽量拿到最终可播地址（如 115 CDN https）。
    避免头显跟随到 127.0.0.1。
    """
    if not url:
        return url

    cache_key = url
    now = time.time()
    if use_cache:
        with _lock:
            hit = _cache.get(cache_key)
            if hit and hit[1] > now:
                return hit[0]

    current = url
    final = url
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
            # 已到 https CDN / 非本服务跳转终点
            host = (urlparse(nxt).hostname or "").lower()
            if code and code < 300:
                break
            if host not in ("127.0.0.1", "localhost", "::1") and urlparse(nxt).scheme == "https":
                # 再跟一次看是否还有跳转
                current = nxt
                try:
                    nxt2, code2 = _follow_once(current)
                    final = nxt2
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

    # 若最终仍是 loopback，改写成局域网 IP（头显可打到本机 12366）
    if lan_host:
        final = rewrite_loopback(final, lan_host)

    if use_cache and final:
        with _lock:
            _cache[cache_key] = (final, now + max(30, ttl))
    return final
