from __future__ import annotations

import time
import urllib.error
import urllib.request
from threading import Lock
from urllib.parse import urljoin, urlparse, urlunparse

_cache: dict[str, tuple[str, float]] = {}
_lock = Lock()
DEFAULT_TTL = 300  # CDN 链接缓存 5 分钟

# 默认只改本机回环；STRM 里若写了旧局域网 IP，请在 config.rewrite_from 里追加
DEFAULT_REWRITE_FROM = ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def normalize_rewrite_from(value: object | None) -> list[str]:
    """支持 list / 逗号分隔字符串。"""
    if value is None:
        return list(DEFAULT_REWRITE_FROM)
    items: list[str] = []
    if isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        raw = str(value).replace(";", ",").split(",")
    for x in raw:
        h = str(x).strip().lower()
        if h:
            items.append(h)
    # 始终保留回环，避免只配了旧 IP 却漏掉 127.0.0.1
    for h in DEFAULT_REWRITE_FROM:
        if h not in items:
            items.append(h)
    return items


def rewrite_loopback(
    url: str,
    lan_host: str,
    rewrite_from: object | None = None,
) -> str:
    """把 STRM 里的源主机（默认 127.0.0.1/localhost，可含旧局域网 IP）改成 rewrite_to。"""
    if not url or not lan_host:
        return url
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if not host:
        return url
    sources = set(normalize_rewrite_from(rewrite_from))
    target = lan_host.strip().lower()
    if host == target:
        return url
    if host not in sources:
        return url
    netloc = lan_host.strip()
    if p.port:
        netloc = f"{netloc}:{p.port}"
    return urlunparse(p._replace(netloc=netloc))


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
    cache_key = f"{url}|{lan_host}|{','.join(normalize_rewrite_from(rewrite_from))}"
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

    if lan_host:
        final = rewrite_loopback(final, lan_host, rewrite_from=rewrite_from)

    if use_cache and final:
        with _lock:
            _cache[cache_key] = (final, now + max(30, ttl))
    return final
