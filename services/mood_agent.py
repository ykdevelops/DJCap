import json
import os
import time
from typing import Any, Dict, List, Optional

from openai import OpenAI

from services.wiki_client import wiki_best_page_minimal


DEFAULT_MODEL = os.getenv("THEMOOD_MODEL", "gpt-4.1")

# --- Safety + caching --------------------------------------------------------
#
# Goal: minimum API calls.
# - One OpenAI call per (artist,title[,secondary]) thanks to caching
# - Wikipedia is fetched minimally (search + single query fetch)

_THEMOOD_CACHE_TTL_SECONDS = 60 * 60 * 6  # 6 hours
_themood_cache: Dict[str, Dict[str, Any]] = {}


FINAL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "track": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "primary": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "artist": {"type": "string"},
                        "title": {"type": "string"},
                        "wiki_title": {"type": "string"},
                        "wiki_url": {"type": "string"},
                    },
                    "required": ["artist", "title", "wiki_title", "wiki_url"],
                },
                "secondary": {
                    "type": ["object", "null"],
                    "additionalProperties": False,
                    "properties": {
                        "artist": {"type": "string"},
                        "title": {"type": "string"},
                        "wiki_title": {"type": "string"},
                        "wiki_url": {"type": "string"},
                    },
                    "required": ["artist", "title", "wiki_title", "wiki_url"],
                },
            },
            "required": ["primary", "secondary"],
        },
        "genres": {"type": "array", "items": {"type": "string"}},
        "theMood": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "label": {"type": "string"},
                "description": {"type": "string"},
                "keywords": {"type": "array", "items": {"type": "string"}, "minItems": 6, "maxItems": 24},
                "scene": {"type": "string"},
                "evidence_phrases": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 10},
            },
            "required": ["label", "description", "keywords", "scene", "evidence_phrases"],
        },
    },
    "required": ["track", "genres", "theMood"],
}


def _instructions(max_keywords: int, max_scene_sentences: int) -> str:
    return f"""
You are theMood, a Wikipedia-only track analysis agent.

Hard rules:
- You may ONLY use the Wikipedia content provided in the prompt. Do NOT use outside knowledge.
- Evidence phrases must be short verbatim fragments pulled from returned Wikipedia text, not invented.
- Keywords must be grounded in the returned Wikipedia text (exact words or tight paraphrases).
- Prefer concrete visual nouns, settings, objects, places, time-period cues, and explicitly described emotions.

Output rules:
- Output MUST match the provided JSON schema exactly (no extra keys).
- keywords length <= {max_keywords}
- scene must be <= {max_scene_sentences} sentences (max).

Mashups:
- If secondary track is provided, blend mood, genres, and visuals from both provided Wikipedia texts.
""".strip()


def _dump_item(item: Any) -> Dict[str, Any]:
    if hasattr(item, "model_dump"):
        return item.model_dump()
    if isinstance(item, dict):
        return item
    # Fallback (best effort)
    return json.loads(json.dumps(item))


def _extract_output_text(resp: Any) -> str:
    # SDK exposes output_text; fall back to scanning output items.
    txt = getattr(resp, "output_text", None)
    if isinstance(txt, str) and txt.strip():
        return txt

    output = getattr(resp, "output", None) or []
    for item in output:
        d = _dump_item(item)
        if d.get("type") == "output_text":
            return str(d.get("text", "") or "")
        if d.get("type") == "message":
            # Some SDK variants put text under content
            content = d.get("content") or []
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "output_text":
                        return str(c.get("text", "") or "")
    return ""


def generate_the_mood(
    artist: str,
    title: str,
    secondary: Optional[Dict[str, str]] = None,
    max_keywords: int = 18,
    max_scene_sentences: int = 2,
) -> Dict[str, Any]:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set (add it to .env or export it)")

    # Cache key: normalized track(s) + limits (limits affect output)
    def norm(s: str) -> str:
        return " ".join(str(s or "").strip().split()).lower()

    sec_sig = ""
    if secondary:
        sec_sig = f"|{norm(secondary.get('artist',''))}|{norm(secondary.get('title',''))}"
    cache_key = f"{norm(artist)}|{norm(title)}{sec_sig}|kw={int(max_keywords)}|sc={int(max_scene_sentences)}"

    cached = _themood_cache.get(cache_key)
    now = time.time()
    if cached and (now - float(cached.get("_ts", 0))) < _THEMOOD_CACHE_TTL_SECONDS:
        return cached["value"]

    client = OpenAI()

    # Minimal Wikipedia fetches (search + single query fetch per track).
    primary_query = f"{title} {artist} song"
    primary_page = wiki_best_page_minimal(primary_query, max_chars=12000)
    if not primary_page:
        # fallback: try without "song"
        primary_page = wiki_best_page_minimal(f"{title} {artist}", max_chars=12000)

    secondary_page = None
    if secondary:
        s_artist = secondary.get("artist", "")
        s_title = secondary.get("title", "")
        secondary_page = wiki_best_page_minimal(f"{s_title} {s_artist} song", max_chars=12000)
        if not secondary_page:
            secondary_page = wiki_best_page_minimal(f"{s_title} {s_artist}", max_chars=12000)

    wiki_bundle = {
        "primary": primary_page,
        "secondary": secondary_page,
    }

    user_prompt = {
        "request": {
            "artist": artist,
            "title": title,
            "secondary": secondary,
            "max_keywords": max_keywords,
            "max_scene_sentences": max_scene_sentences,
        },
        "wikipedia": wiki_bundle,
    }

    final = client.responses.create(
        model=DEFAULT_MODEL,
        input=[
            {
                "role": "user",
                "content": (
                    "Use ONLY the provided Wikipedia text to produce theMood JSON.\n"
                    f"{json.dumps(user_prompt, ensure_ascii=False)}"
                ),
            }
        ],
        instructions=_instructions(max_keywords=max_keywords, max_scene_sentences=max_scene_sentences),
        text={
            "format": {
                "type": "json_schema",
                "name": "theMoodResponse",
                "strict": True,
                "schema": FINAL_SCHEMA,
            }
        },
    )

    out = _extract_output_text(final).strip()
    if not out:
        raise RuntimeError("OpenAI response contained no output text")

    value = json.loads(out)

    # Enforce runtime caps as an extra safety net.
    kw = value.get("theMood", {}).get("keywords")
    if isinstance(kw, list):
        value["theMood"]["keywords"] = kw[: max(6, int(max_keywords))]

    _themood_cache[cache_key] = {"_ts": now, "value": value}
    return value


