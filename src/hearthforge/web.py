"""Internet access: web search and page fetch with SSRF protection.

Everything returned is UNTRUSTED data. Fetching only reaches PUBLIC addresses: loopback, private,
link-local and reserved ranges are refused, including after redirects. (Residual risk: DNS can change
between our check and the connection; see docs/PRIVACY_AND_SECURITY.md.)
"""
from __future__ import annotations

import html
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, urljoin, urlparse

import httpx

UA = "Mozilla/5.0 (compatible; Hearthforge/0.1; +local)"
MAX_BYTES = 1_500_000


class WebError(Exception):
    pass


def _public(ip: str) -> bool:
    a = ipaddress.ip_address(ip)
    return not (a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_multicast or a.is_unspecified)


def default_resolver(host: str) -> list[str]:
    return [i[4][0] for i in socket.getaddrinfo(host, None)]


def check_url(url: str, resolver=default_resolver, allow_private: bool = False) -> str:
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise WebError("Only http(s) URLs are allowed")
    if u.username or u.password:
        raise WebError("URLs with embedded credentials are refused")
    if allow_private:
        return url
    try:
        ips = [str(ipaddress.ip_address(u.hostname))]
    except ValueError:
        try:
            ips = resolver(u.hostname)
        except OSError:
            raise WebError(f"Cannot resolve host {u.hostname}")
    if not ips or not all(_public(i) for i in ips):
        raise WebError("Refused: that address is not on the public internet (local/private addresses are blocked)")
    return url


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head", "template"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "pre", "table", "ul", "ol"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.out.append(data)


def html_to_text(src: str) -> tuple[str, str]:
    p = _Text()
    try:
        p.feed(src)
    except Exception:
        pass
    text = "".join(p.out)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return p.title.strip(), text


async def fetch(url: str, *, max_chars: int = 12000, timeout: float = 15, transport=None, resolver=default_resolver) -> dict:
    cur = check_url(url, resolver)
    async with httpx.AsyncClient(transport=transport, timeout=timeout, follow_redirects=False, headers={"User-Agent": UA}) as c:
        for _ in range(5):
            try:
                async with c.stream("GET", cur) as r:
                    if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                        cur = check_url(urljoin(cur, r.headers["location"]), resolver)
                        continue
                    ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                    buf = bytearray()
                    async for chunk in r.aiter_bytes():
                        buf.extend(chunk)
                        if len(buf) > MAX_BYTES:
                            break
                    if r.status_code >= 400:
                        raise WebError(f"HTTP {r.status_code} from {urlparse(cur).hostname}")
                    if ctype and not (ctype.startswith("text/") or ctype in ("application/json", "application/xml", "application/xhtml+xml", "application/rss+xml", "application/atom+xml")):
                        raise WebError(f"Unsupported content type '{ctype}' (only text, HTML, JSON and XML are read)")
                    raw = bytes(buf[:MAX_BYTES]).decode(r.encoding or "utf-8", errors="replace")
                    title, text = html_to_text(raw) if ("html" in ctype or raw.lstrip()[:15].lower().startswith(("<!doctype", "<html"))) else ("", raw)
                    return {"url": url, "final_url": cur, "title": title, "text": text[:max_chars], "truncated": len(text) > max_chars or len(buf) > MAX_BYTES}
            except httpx.TimeoutException:
                raise WebError("Timed out fetching the page")
            except httpx.HTTPError as e:
                raise WebError(f"Network error: {type(e).__name__}")
        raise WebError("Too many redirects")


# ------------------------------------------------------------------ search engines
class _DDG(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results: list[dict] = []
        self._mode = None
        self._cur: dict | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""
        if tag == "a" and "result__a" in cls:
            self._cur = {"title": "", "url": _ddg_url(a.get("href", "")), "snippet": ""}
            self.results.append(self._cur)
            self._mode = "title"
        elif tag in ("a", "div", "td") and "result__snippet" in cls and self._cur is not None:
            self._mode = "snippet"

    def handle_endtag(self, tag):
        if tag == "a" and self._mode == "title":
            self._mode = None
        elif tag in ("a", "div", "td") and self._mode == "snippet":
            self._mode = None

    def handle_data(self, data):
        if self._cur is not None and self._mode:
            self._cur[self._mode] += data


def _ddg_url(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    q = parse_qs(urlparse(href).query)
    return q["uddg"][0] if "uddg" in q else href


def parse_ddg(page: str, limit: int) -> list[dict]:
    p = _DDG()
    p.feed(page)
    out = []
    for r in p.results:
        if r["url"].startswith("http") and "duckduckgo.com/y.js" not in r["url"]:
            out.append({"title": " ".join(r["title"].split()), "url": r["url"], "snippet": " ".join(r["snippet"].split())})
    return out[:limit]


async def search(query: str, engine: str = "duckduckgo", searxng_url: str = "", limit: int = 6, transport=None) -> list[dict]:
    q = query.strip()
    if not q:
        raise WebError("Empty query")
    async with httpx.AsyncClient(transport=transport, timeout=15, follow_redirects=True, headers={"User-Agent": UA}) as c:
        try:
            if engine == "duckduckgo":
                r = await c.post("https://html.duckduckgo.com/html/", data={"q": q})
                r.raise_for_status()
                res = parse_ddg(r.text, limit)
                if not res:
                    raise WebError("DuckDuckGo returned no parsable results (it may be rate-limiting or blocking automated queries). Try another engine in Internet settings.")
                return res
            if engine == "searxng":
                if not searxng_url:
                    raise WebError("Set your SearXNG URL in Internet settings first")
                u = check_url(searxng_url.rstrip("/") + "/search", allow_private=True)
                r = await c.get(u, params={"q": q, "format": "json"})
                r.raise_for_status()
                return [{"title": x.get("title", ""), "url": x.get("url", ""), "snippet": x.get("content", "")} for x in r.json().get("results", [])[:limit]]
            if engine == "wikipedia":
                r = await c.get("https://en.wikipedia.org/w/api.php", params={"action": "query", "list": "search", "srsearch": q, "format": "json", "srlimit": limit})
                r.raise_for_status()
                return [{"title": x["title"], "url": "https://en.wikipedia.org/wiki/" + quote(x["title"].replace(" ", "_")),
                         "snippet": html.unescape(re.sub(r"<[^>]+>", "", x.get("snippet", "")))} for x in r.json()["query"]["search"]]
        except httpx.HTTPStatusError as e:
            raise WebError(f"Search engine returned HTTP {e.response.status_code}")
        except httpx.TimeoutException:
            raise WebError("Search timed out")
        except httpx.HTTPError as e:
            raise WebError(f"Cannot reach the search engine ({type(e).__name__}). Check your internet connection.")
        except (KeyError, ValueError):
            raise WebError("Unexpected response from the search engine")
    raise WebError(f"Unknown engine '{engine}'")
