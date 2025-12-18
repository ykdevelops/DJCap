import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

import requests

WIKI_API_URL = "https://en.wikipedia.org/w/api.php"

WIKI_HEADERS = {
    # Wikipedia API etiquette: send a descriptive User-Agent.
    # See: https://www.mediawiki.org/wiki/API:Etiquette
    "User-Agent": "DjCap/1.0 (local dev; Wikipedia-only theMood)",
    "Accept": "application/json",
}


DEFAULT_PREFERRED_SECTIONS: List[str] = [
    "Lyrics and composition",
    "Composition",
    "Lyrics",
    "Music video",
    "Background",
    "Release",
    "Production",
    "Recording",
]


class _HTMLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: List[str] = []

    def handle_data(self, data: str) -> None:  # noqa: D401
        if data:
            self._chunks.append(data)

    def text(self) -> str:
        return "".join(self._chunks)


def _strip_html(html: str) -> str:
    s = _HTMLStripper()
    s.feed(html or "")
    txt = s.text()
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


@dataclass(frozen=True)
class _CacheKey:
    pageid: int
    sections_sig: str
    max_chars: int


class _TTLCache:
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._data: Dict[_CacheKey, Tuple[float, Dict[str, Any]]] = {}

    def get(self, key: _CacheKey) -> Optional[Dict[str, Any]]:
        item = self._data.get(key)
        if not item:
            return None
        ts, val = item
        if (time.time() - ts) > self._ttl:
            self._data.pop(key, None)
            return None
        return val

    def set(self, key: _CacheKey, value: Dict[str, Any]) -> None:
        self._data[key] = (time.time(), value)


_cache = _TTLCache(ttl_seconds=60 * 60 * 4)  # 4 hours


def wiki_search(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    params = {
        "action": "query",
        "format": "json",
        "list": "search",
        "srsearch": query,
        "srlimit": str(limit),
        "srprop": "snippet",
    }
    r = requests.get(WIKI_API_URL, params=params, headers=WIKI_HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()

    results: List[Dict[str, Any]] = []
    for item in (data.get("query", {}).get("search", []) or []):
        results.append(
            {
                "title": item.get("title", "") or "",
                "pageid": int(item.get("pageid", 0) or 0),
                "snippet": _strip_html(item.get("snippet", "") or ""),
            }
        )
    return results


def wiki_fetch_page_minimal(pageid: int, max_chars: int = 12000, wiki_title: str = "") -> Dict[str, Any]:
    """
    Minimal single-call page fetch (after you know the pageid):
    - Plaintext extract (full page or long lead depending on exintro)
    - Canonical URL
    - Categories (non-hidden)
    """
    key = _CacheKey(pageid=pageid, sections_sig="__minimal__", max_chars=max_chars)
    cached = _cache.get(key)
    if cached:
        if wiki_title:
            cached = dict(cached)
            cached["title"] = wiki_title
        return cached

    params = {
        "action": "query",
        "format": "json",
        "pageids": str(pageid),
        "prop": "extracts|categories|info",
        "inprop": "url",
        "explaintext": "1",
        "exchars": str(max_chars),
        "exsectionformat": "plain",
        "cllimit": "50",
        "clshow": "!hidden",
    }
    r = requests.get(WIKI_API_URL, params=params, headers=WIKI_HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    page = (data.get("query", {}).get("pages", {}) or {}).get(str(pageid), {}) or {}

    extract = (page.get("extract") or "").strip()
    full_url = (page.get("fullurl") or "").strip()
    cats = page.get("categories", []) or []
    categories: List[str] = []
    for c in cats:
        t = (c.get("title", "") or "").strip()
        if t.startswith("Category:"):
            t = t[len("Category:") :]
        if t:
            categories.append(t)

    payload: Dict[str, Any] = {
        "title": wiki_title or (page.get("title", "") or ""),
        "pageid": pageid,
        "url": full_url or f"https://en.wikipedia.org/?curid={pageid}",
        # Keep existing shape used by theMood code: lead + sections
        "lead": extract,
        "sections": {},
        "categories": categories,
    }
    _cache.set(key, payload)
    return payload


def wiki_best_page_minimal(query: str, max_chars: int = 12000) -> Optional[Dict[str, Any]]:
    """
    Minimal “search then fetch” helper. This is the lowest-cost Wikipedia path:
    - 1x search
    - 1x query fetch for the chosen page
    """
    results = wiki_search(query, limit=5)
    if not results:
        return None

    def score(r: Dict[str, Any]) -> int:
        t = (r.get("title", "") or "").lower()
        s = 0
        if "(song)" in t:
            s += 5
        if "(single)" in t:
            s += 3
        if "(album)" in t:
            s += 1
        return s

    best = sorted(results, key=score, reverse=True)[0]
    pageid = int(best.get("pageid", 0) or 0)
    if not pageid:
        return None
    return wiki_fetch_page_minimal(pageid=pageid, max_chars=max_chars, wiki_title=best.get("title", "") or "")


def _wiki_list_sections(pageid: int) -> List[Dict[str, Any]]:
    params = {
        "action": "parse",
        "format": "json",
        "pageid": str(pageid),
        "prop": "sections",
        "redirects": "1",
    }
    r = requests.get(WIKI_API_URL, params=params, headers=WIKI_HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    return (data.get("parse", {}).get("sections", []) or [])


def _wiki_parse_section_html(pageid: int, section_index: str) -> str:
    params = {
        "action": "parse",
        "format": "json",
        "pageid": str(pageid),
        "prop": "text",
        "section": str(section_index),
        "redirects": "1",
    }
    r = requests.get(WIKI_API_URL, params=params, headers=WIKI_HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    return (data.get("parse", {}).get("text", {}).get("*", "") or "")


def _wiki_categories(pageid: int, limit: int = 50) -> List[str]:
    params = {
        "action": "query",
        "format": "json",
        "pageids": str(pageid),
        "prop": "categories",
        "cllimit": str(limit),
        "clshow": "!hidden",
    }
    r = requests.get(WIKI_API_URL, params=params, headers=WIKI_HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    page = (data.get("query", {}).get("pages", {}) or {}).get(str(pageid), {}) or {}
    cats = page.get("categories", []) or []

    out: List[str] = []
    for c in cats:
        t = (c.get("title", "") or "").strip()
        if t.startswith("Category:"):
            t = t[len("Category:") :]
        if t:
            out.append(t)
    return out


def wiki_get_page_extract(
    pageid: int,
    section_titles: Optional[List[str]] = None,
    preferred_sections: Optional[List[str]] = None,
    max_chars_per_page: int = 12000,
    wiki_title: str = "",
) -> Dict[str, Any]:
    section_titles = section_titles or []
    preferred_sections = preferred_sections or DEFAULT_PREFERRED_SECTIONS

    sig = "|".join([s.strip().lower() for s in section_titles if s and s.strip()])
    key = _CacheKey(pageid=pageid, sections_sig=sig, max_chars=max_chars_per_page)
    cached = _cache.get(key)
    if cached:
        # keep title fresh (from caller search result)
        if wiki_title:
            cached = dict(cached)
            cached["title"] = wiki_title
        return cached

    sections = _wiki_list_sections(pageid)
    title_to_idx: Dict[str, str] = {}
    for s in sections:
        line = (s.get("line") or "").strip()
        idx = str(s.get("index") or "").strip()
        if line and idx:
            title_to_idx[line.lower()] = idx

    # Lead is always section 0
    lead_html = _wiki_parse_section_html(pageid, "0")
    lead_text = _strip_html(lead_html)

    # Choose sections: explicit first, then preferred
    chosen_titles: List[str] = []
    for t in section_titles:
        if not t:
            continue
        if t.strip().lower() in title_to_idx and t.strip() not in chosen_titles:
            chosen_titles.append(t.strip())

    for t in preferred_sections:
        if len(chosen_titles) >= 6:
            break
        if t.strip().lower() in title_to_idx and t.strip() not in chosen_titles:
            chosen_titles.append(t.strip())

    section_texts: Dict[str, str] = {}
    for t in chosen_titles:
        idx = title_to_idx.get(t.lower())
        if not idx:
            continue
        html = _wiki_parse_section_html(pageid, idx)
        txt = _strip_html(html)
        if txt:
            section_texts[t] = txt

    cats = _wiki_categories(pageid)
    url = f"https://en.wikipedia.org/?curid={pageid}"

    def cap(s: str) -> str:
        return (s or "")[:max_chars_per_page]

    payload: Dict[str, Any] = {
        "title": wiki_title or "",
        "pageid": pageid,
        "url": url,
        "lead": cap(lead_text),
        "sections": {k: cap(v) for k, v in section_texts.items()},
        "categories": cats,
    }

    _cache.set(key, payload)
    return payload


def wikipedia_fetch_impl(
    queries: List[str],
    preferred_sections: Optional[List[str]] = None,
    max_chars_per_page: int = 12000,
) -> Dict[str, Any]:
    """
    Tool implementation for the agent:
    - For each query, run Wikipedia search and fetch the best matching page extract.
    """
    preferred_sections = preferred_sections or DEFAULT_PREFERRED_SECTIONS

    searches: List[Dict[str, Any]] = []
    pages: List[Dict[str, Any]] = []

    for q in (queries or [])[:2]:
        q = str(q or "").strip()
        if not q:
            continue

        results = wiki_search(q, limit=5)
        searches.append({"query": q, "results": results})

        if not results:
            continue

        # Heuristic: prefer (song) pages when present.
        def score(r: Dict[str, Any]) -> int:
            t = (r.get("title", "") or "").lower()
            s = 0
            if "(song)" in t:
                s += 5
            if "(single)" in t:
                s += 3
            if "(album)" in t:
                s += 1
            return s

        best = sorted(results, key=score, reverse=True)[0]
        pageid = int(best.get("pageid", 0) or 0)
        if not pageid:
            continue

        page = wiki_get_page_extract(
            pageid=pageid,
            section_titles=None,
            preferred_sections=preferred_sections,
            max_chars_per_page=max_chars_per_page,
            wiki_title=best.get("title", "") or "",
        )
        pages.append(page)

    return {"searches": searches, "pages": pages}


