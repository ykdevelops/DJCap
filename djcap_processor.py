#!/usr/bin/env python3
"""
DjCap JSON Watcher and Metadata Processor
Monitors djcap_output.json for changes and enriches metadata with Last.fm tags,
keyword analysis, and GIFs.
"""
import json
import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
import os
import re
from collections import deque
import random

# #region agent log
DEBUG_LOG_PATH = Path(__file__).parent / ".cursor" / "debug.log"
def _debug_log(location, message, data, hypothesis_id):
    try:
        DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_LOG_PATH, 'a') as f:
            log_entry = {
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": hypothesis_id,
                "location": location,
                "message": message,
                "data": data,
                "timestamp": int(time.time() * 1000)
            }
            f.write(json.dumps(log_entry) + "\n")
    except: pass
# #endregion

# Load API keys early (loads repo-root `.env` via python-dotenv).
# Important: AudioApis `metadata.giphy_client` imports its own `config` module and reads
# `GIPHY_API_KEY` at import time. If we import AudioApis first, it can cache an empty key.
from src.config import LASTFM_API_KEY, GIPHY_API_KEY

# Add AudioApis to Python path
AUDIOAPIS_PATH = '/Users/youssefkhalil/AudioApis'
if os.path.exists(AUDIOAPIS_PATH):
    sys.path.insert(0, AUDIOAPIS_PATH)

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    logging.warning("watchdog not available. Install with: pip install watchdog")
    # Ensure this name exists so the module can import/run without crashing.
    FileSystemEventHandler = object  # type: ignore[misc,assignment]

# Import AudioApis metadata modules
try:
    from metadata.lastfm_client import get_lastfm_tags
    from metadata.keyword_analyzer import analyze_keywords
    from metadata.giphy_client import fetch_gifs_for_keywords
    METADATA_MODULES_AVAILABLE = True
except ImportError as e:
    METADATA_MODULES_AVAILABLE = False
    logging.warning(f"AudioApis metadata modules not available: {e}")

# Direct Giphy API implementation (fallback when AudioApis not available)
def _fetch_gifs_direct(query: str, limit: int = 25) -> List[Dict[str, Any]]:
    """
    Direct Giphy API implementation that doesn't require AudioApis.
    Returns list of GIF dicts with id, url, title, tags, etc.
    """
    if not GIPHY_API_KEY or not query:
        return []
    
    try:
        import urllib.request
        import urllib.parse
        
        # Giphy Search API endpoint
        base_url = "https://api.giphy.com/v1/gifs/search"
        params = {
            "api_key": GIPHY_API_KEY,
            "q": query,
            "limit": min(limit, 50),  # Giphy max is 50
            "rating": "g",  # Safe for work
            "lang": "en"
        }
        
        url = f"{base_url}?{urllib.parse.urlencode(params)}"
        
        # #region agent log
        _debug_log("djcap_processor.py:_fetch_gifs_direct", "Fetching from Giphy API", {"query": query, "limit": limit, "url": url.replace(GIPHY_API_KEY, "***")}, "J")
        # #endregion
        
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())
            
        gifs = []
        if data.get("data"):
            for item in data["data"]:
                gif = {
                    "id": item.get("id"),
                    "url": item.get("images", {}).get("downsized", {}).get("url") or item.get("images", {}).get("fixed_height", {}).get("url") or "",
                    "title": item.get("title", ""),
                    "rating": item.get("rating", "g"),
                    "source": item.get("source", ""),
                    "width": item.get("images", {}).get("downsized", {}).get("width") or item.get("images", {}).get("fixed_height", {}).get("width") or 480,
                    "height": item.get("images", {}).get("downsized", {}).get("height") or item.get("images", {}).get("fixed_height", {}).get("height") or 270,
                    "tags": item.get("tags", [])
                }
                if gif["url"]:  # Only add if we have a valid URL
                    gifs.append(gif)
        
        # #region agent log
        _debug_log("djcap_processor.py:_fetch_gifs_direct", "Giphy API response", {"gifs_count": len(gifs)}, "J")
        # #endregion
        
        return gifs
    except Exception as e:
        # #region agent log
        _debug_log("djcap_processor.py:_fetch_gifs_direct", "Giphy API error", {"error": str(e), "error_type": type(e).__name__}, "J")
        # #endregion
        logger.warning(f"Error fetching GIFs directly from Giphy API: {e}")
        return []

from src.key_translator import translate_key_to_characteristics
from src.output_cleanup import cleanup_output_folder
from src.dance_video_bank import get_dance_videos

# Configuration: Set to False to skip API calls entirely (faster, no external dependencies)
USE_LASTFM_API = False  # Set to False to skip Last.fm API calls
USE_GIPHY_API = True   # Enable live Giphy API calls for GIF fetching
USE_KEYWORD_ANALYZER = False  # Set to False to skip keyword analyzer (use basic keywords: title, artist, key characteristics)

# Offline / fallback GIF support
USE_OFFLINE_GIF_BANK = False  # Disabled - use Giphy API only

# Giphy API configuration
# Fetch exactly N GIFs per track (safe default: 5)
GIPHY_GIFS_PER_TRACK = 5

# Fetch a larger pool per track (still one request) so we can avoid reusing the same
# GIFs for the same artist across consecutive tracks. Final output is still capped to 5.
GIPHY_FETCH_POOL_SIZE = int(os.getenv("GIPHY_FETCH_POOL_SIZE", "25"))
GIPHY_FETCH_POOL_SIZE = max(GIPHY_GIFS_PER_TRACK, min(50, GIPHY_FETCH_POOL_SIZE))

# Persist a small per-artist history of GIF IDs to reduce repetition across tracks.
GIPHY_HISTORY_PATH = Path(__file__).resolve().parent / "data" / "output" / "giphy_history.json"
GIPHY_HISTORY_MAX_IDS_PER_ARTIST = int(os.getenv("GIPHY_HISTORY_MAX_IDS_PER_ARTIST", "200"))
GIPHY_HISTORY_MAX_IDS_PER_ARTIST = max(20, min(2000, GIPHY_HISTORY_MAX_IDS_PER_ARTIST))

_GIPHY_HISTORY_LOADED = False
_GIPHY_HISTORY: Dict[str, deque] = {}

# Hard cap: maximum number of live Giphy requests per rolling hour.
# Persisted to disk so restarts don't reset the quota usage.
GIPHY_MAX_REQUESTS_PER_HOUR = int(os.getenv("GIPHY_MAX_REQUESTS_PER_HOUR", "40"))
GIPHY_RATE_STATE_PATH = Path(__file__).resolve().parent / "data" / "output" / "giphy_rate_state.json"

_GIPHY_RATE_LOADED = False
_GIPHY_RATE_TS = deque()


def _ensure_giphy_rate_loaded() -> None:
    """Load persisted request timestamps once (best-effort)."""
    global _GIPHY_RATE_LOADED, _GIPHY_RATE_TS
    if _GIPHY_RATE_LOADED:
        return
    try:
        if GIPHY_RATE_STATE_PATH.exists():
            data = json.loads(GIPHY_RATE_STATE_PATH.read_text())
            ts = data.get("timestamps", [])
            parsed = []
            for t in ts:
                if isinstance(t, (int, float)):
                    parsed.append(float(t))
                elif isinstance(t, str):
                    try:
                        parsed.append(float(t))
                    except Exception:
                        pass
            parsed.sort()
            _GIPHY_RATE_TS = deque(parsed)
    except Exception:
        _GIPHY_RATE_TS = deque()
    _GIPHY_RATE_LOADED = True


def _giphy_prune(now: float) -> None:
    """Drop timestamps older than 1 hour."""
    cutoff = now - 3600.0
    while _GIPHY_RATE_TS and _GIPHY_RATE_TS[0] < cutoff:
        _GIPHY_RATE_TS.popleft()


def _giphy_can_request(cost: int = 1) -> bool:
    _ensure_giphy_rate_loaded()
    now = time.time()
    _giphy_prune(now)
    return (len(_GIPHY_RATE_TS) + cost) <= GIPHY_MAX_REQUESTS_PER_HOUR


def _giphy_record_request(cost: int = 1) -> None:
    _ensure_giphy_rate_loaded()
    now = time.time()
    _giphy_prune(now)
    for _ in range(max(1, cost)):
        _GIPHY_RATE_TS.append(now)
    try:
        GIPHY_RATE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        GIPHY_RATE_STATE_PATH.write_text(json.dumps({"timestamps": list(_GIPHY_RATE_TS)}, indent=2))
    except Exception:
        # Best effort only: don't fail enrichment if persistence fails
        pass


def _clean_title_for_giphy(title: Optional[str]) -> Optional[str]:
    """Normalize a track title for use in the Giphy query."""
    if not title:
        return None
    cleaned = str(title)
    cleaned = re.sub(r"\s*\([^)]*\)", "", cleaned)  # remove parentheticals
    cleaned = re.sub(r"\s+feat\.?.*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+ft\.?.*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip()
    return cleaned or None


def _build_giphy_query_parts(title: Optional[str], artist: Optional[str]) -> List[str]:
    """
    Build the Giphy search "keywords" list.
    
    Policy: artist-only search (no title) to keep results broad and consistent.
    """
    if not artist:
        return []
    a = str(artist).strip()
    return [a] if a else []


def _normalize_artist_key(artist: Optional[str]) -> str:
    return (str(artist).strip().lower() if artist else "").strip()


def _ensure_giphy_history_loaded() -> None:
    """Load persisted per-artist GIF ID history once (best-effort)."""
    global _GIPHY_HISTORY_LOADED, _GIPHY_HISTORY
    if _GIPHY_HISTORY_LOADED:
        return
    _GIPHY_HISTORY = {}
    try:
        if GIPHY_HISTORY_PATH.exists():
            data = json.loads(GIPHY_HISTORY_PATH.read_text())
            if isinstance(data, dict):
                for k, ids in data.items():
                    if not isinstance(k, str) or not isinstance(ids, list):
                        continue
                    cleaned = [str(x) for x in ids if x]
                    _GIPHY_HISTORY[k] = deque(cleaned[-GIPHY_HISTORY_MAX_IDS_PER_ARTIST:])
    except Exception:
        _GIPHY_HISTORY = {}
    _GIPHY_HISTORY_LOADED = True


def _save_giphy_history() -> None:
    try:
        GIPHY_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: list(v) for k, v in _GIPHY_HISTORY.items()}
        GIPHY_HISTORY_PATH.write_text(json.dumps(payload, indent=2))
    except Exception:
        pass


def _filter_and_select_gifs_for_artist(
    artist: Optional[str],
    gifs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Prefer GIFs not recently used for the same artist.
    Returns <= GIPHY_GIFS_PER_TRACK and records selections to history.
    """
    if not gifs:
        return []

    _ensure_giphy_history_loaded()
    artist_key = _normalize_artist_key(artist)
    used_ids = set(_GIPHY_HISTORY.get(artist_key, deque())) if artist_key else set()

    # De-dupe within this batch first
    seen = set()
    unique: List[Dict[str, Any]] = []
    for g in gifs:
        gid = g.get("id") or g.get("url") or ""
        if not gid or gid in seen:
            continue
        seen.add(gid)
        unique.append(g)

    # Shuffle so we don't always pick the same "top" items
    random.shuffle(unique)

    fresh: List[Dict[str, Any]] = []
    fallback: List[Dict[str, Any]] = []
    for g in unique:
        gid = g.get("id") or g.get("url") or ""
        if artist_key and gid in used_ids:
            fallback.append(g)
        else:
            fresh.append(g)

    selected = (fresh + fallback)[:GIPHY_GIFS_PER_TRACK]

    if artist_key:
        q = _GIPHY_HISTORY.get(artist_key)
        if q is None:
            q = deque()
            _GIPHY_HISTORY[artist_key] = q
        for g in selected:
            gid = g.get("id") or g.get("url") or ""
            if gid:
                q.append(gid)
        while len(q) > GIPHY_HISTORY_MAX_IDS_PER_ARTIST:
            q.popleft()
        _save_giphy_history()

    return selected


def _dedupe_gif_list(gifs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """De-dupe GIFs by (id or url) while preserving order."""
    seen = set()
    unique: List[Dict[str, Any]] = []
    for g in gifs or []:
        gid = g.get("id") or g.get("url") or ""
        if not gid or gid in seen:
            continue
        seen.add(gid)
        unique.append(g)
    return unique


def _enriched_gif_policy_stale(deck_data: Dict[str, Any], enriched: Dict[str, Any]) -> bool:
    """
    Return True if the currently stored enriched payload doesn't match our current GIF policy.
    This lets us refresh current_enriched even when the track is the "same" (e.g. after config changes).
    """
    desired_parts = _build_giphy_query_parts(deck_data.get("title"), deck_data.get("artist"))
    qp = enriched.get("giphy_query_parts")
    qp_ok = isinstance(qp, list) and qp[: len(desired_parts)] == desired_parts
    gifs = enriched.get("gifs")
    gifs_ok = isinstance(gifs, list) and len(gifs) <= GIPHY_GIFS_PER_TRACK if desired_parts else True
    pool = enriched.get("gif_pool")
    # Ensure we have a pool to support interactive replacements.
    pool_ok = isinstance(pool, list) and (len(pool) >= len(gifs or []) if desired_parts else True)
    return (not qp_ok) or (not gifs_ok) or (not pool_ok)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
DJCAP_JSON_FILE = "/Users/youssefkhalil/AudioGiphy/data/output/djcap_output.json"
DEBOUNCE_DELAY = 0.1  # seconds to wait after file change before processing
RUNNING = True

# Cleanup configuration
CLEANUP_CHECK_INTERVAL = 100  # Check every N processing cycles
OUTPUT_FOLDER = "/Users/youssefkhalil/AudioGiphy/data/output"

# Track last processed file to avoid duplicates
_last_processed_time = 0
_last_processed_content = None
_last_active_deck = None  # Track which deck was active last time
_last_deck1_active = None  # Track deck1 active status
_last_deck2_active = None  # Track deck2 active status


def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully."""
    global RUNNING
    logger.info("Received interrupt signal, shutting down...")
    RUNNING = False
    sys.exit(0)


def read_djcap_json(file_path: str, max_retries: int = 5, retry_delay: float = 0.1) -> Optional[Dict[str, Any]]:
    """
    Safely read JSON file, handling atomic writes.
    
    Args:
        file_path: Path to JSON file
        max_retries: Maximum number of retries if file is locked
        retry_delay: Delay between retries in seconds
        
    Returns:
        Parsed JSON dictionary or None if read fails
    """
    temp_file = f"{file_path}.tmp"
    
    for attempt in range(max_retries):
        try:
            # Check if temp file exists (atomic write in progress)
            if os.path.exists(temp_file):
                time.sleep(retry_delay)
                continue
            
            # Read the JSON file
            with open(file_path, 'r') as f:
                content = f.read().strip()
                if not content:
                    logger.debug("JSON file is empty")
                    return None
                
                data = json.loads(content)
                return data
                
        except json.JSONDecodeError as e:
            logger.warning(f"JSON decode error (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                logger.error(f"Failed to read JSON after {max_retries} attempts")
                return None
                
        except FileNotFoundError:
            logger.warning(f"JSON file not found: {file_path}")
            return None
            
        except Exception as e:
            logger.error(f"Error reading JSON file: {e}", exc_info=True)
            return None
    
    return None


def enrich_deck_data(deck_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enrich a single deck's data with keywords, tags, and GIFs.
    Only enriches if deck is active.
    
    Args:
        deck_data: Dictionary with deck metadata (title, artist, bpm, key, active)
        
    Returns:
        Enriched deck data with additional fields (or basic data if inactive)
    """
    # #region agent log
    _debug_log("djcap_processor.py:enrich_deck_data", "Function entry", {"active": deck_data.get('active'), "title": deck_data.get('title'), "artist": deck_data.get('artist')}, "I")
    # #endregion
    
    if not deck_data.get('active', False):
        # #region agent log
        _debug_log("djcap_processor.py:enrich_deck_data", "Deck not active, returning basic data", {}, "I")
        # #endregion
        # If deck is not active, return only basic metadata
        return {
            'deck': deck_data.get('deck'),
            'title': deck_data.get('title'),
            'artist': deck_data.get('artist'),
            'bpm': deck_data.get('bpm'),
            'key': deck_data.get('key'),
            'active': False
        }
    
    title = deck_data.get('title')
    artist = deck_data.get('artist')
    bpm = deck_data.get('bpm')
    key = deck_data.get('key')
    
    # #region agent log
    _debug_log("djcap_processor.py:enrich_deck_data", "Enriching active deck", {"title": title, "artist": artist, "bpm": bpm, "key": key}, "I")
    # #endregion
    logger.info(f"Enriching active deck: {title} - {artist}")
    
    # Build keyword collection
    keyword_collection = []
    key_characteristics = []
    
    if title:
        keyword_collection.append(title)
    if artist:
        keyword_collection.append(artist)
    if key:
        key_characteristics = translate_key_to_characteristics(key)
        keyword_collection.extend(key_characteristics)
        logger.info(f"Translated key '{key}' to characteristics: {key_characteristics}")
    
    # Get Last.fm tags (optional - skip if disabled or no API key)
    lastfm_tags = []
    if USE_LASTFM_API and METADATA_MODULES_AVAILABLE and LASTFM_API_KEY and artist and title:
        try:
            logger.info(f"Fetching Last.fm tags for: {artist} - {title}")
            lastfm_tags = get_lastfm_tags(artist, title)
            logger.info(f"Got {len(lastfm_tags)} Last.fm tags: {lastfm_tags}")
        except Exception as e:
            logger.warning(f"Error fetching Last.fm tags (skipping): {e}")
    else:
        logger.debug("Skipping Last.fm tags (disabled or no API key)")
    
    # Analyze keywords (optional - use basic keywords if disabled or analyzer not available)
    refined_keywords = keyword_collection  # Start with title, artist, key characteristics
    keyword_scores = {}
    if USE_KEYWORD_ANALYZER and METADATA_MODULES_AVAILABLE:
        try:
            ocr_metadata = {'title': title, 'artist': artist, 'bpm': bpm, 'key': key}
            logger.info("Analyzing keywords...")
            result = analyze_keywords(ocr_metadata=ocr_metadata, lastfm_tags=lastfm_tags, bpm=bpm, key=key)
            if isinstance(result, tuple) and len(result) == 2:
                keywords, scores = result
                refined_keywords = list(set(keyword_collection + keywords))
                keyword_scores = scores
            logger.info(f"Final keywords: {refined_keywords}")
        except Exception as e:
            logger.warning(f"Error analyzing keywords (using basic keywords): {e}")
            # Use basic keyword collection if analyzer fails
            refined_keywords = keyword_collection
    else:
        logger.debug("Using basic keywords (title, artist, key characteristics) - no API calls")
    
    # Build EXACTLY ONE Giphy query per track (artist-only policy)
    query_parts: List[str] = _build_giphy_query_parts(title, artist)
    query = " ".join(query_parts).strip() if query_parts else None

    # #region agent log
    _debug_log("djcap_processor.py:enrich_deck_data", "Giphy query built", {"query_parts": query_parts, "query": query, "USE_GIPHY_API": USE_GIPHY_API, "METADATA_MODULES_AVAILABLE": METADATA_MODULES_AVAILABLE, "GIPHY_API_KEY": bool(GIPHY_API_KEY)}, "J")
    # #endregion

    search_keywords: List[str] = [query] if query else []
    # Fetch a larger pool (still one request) so we can avoid reusing the same GIFs
    # for the same artist across consecutive tracks. Final output is still capped to 5.
    per_keyword_limit = GIPHY_FETCH_POOL_SIZE

    gifs: List[Dict[str, Any]] = []
    gif_pool: List[Dict[str, Any]] = []

    # Primary: live Giphy API (if enabled)
    # Also avoid re-fetch loops: if this deck already has gifs for the same query, reuse them.
    existing_query = deck_data.get("giphy_query")
    existing_gifs = deck_data.get("gifs")
    existing_pool = deck_data.get("gif_pool")
    # #region agent log
    _debug_log("djcap_processor.py:enrich_deck_data", "Checking existing GIFs", {"existing_query": existing_query, "existing_gifs_count": len(existing_gifs) if isinstance(existing_gifs, list) else 0, "query_match": existing_query == query}, "J")
    # #endregion
    should_reuse = False
    if isinstance(existing_gifs, list) and existing_gifs and existing_query and existing_query == query:
        # When reusing, we need to extract only GIFs (not videos) from the interleaved list
        # Filter out videos (items with mime='video/mp4' or source='dance_mp4_bank')
        gif_only_list = [g for g in existing_gifs if g.get('mime') != 'video/mp4' and g.get('source') != 'dance_mp4_bank']
        if len(gif_only_list) >= GIPHY_GIFS_PER_TRACK:
            gifs = gif_only_list[:GIPHY_GIFS_PER_TRACK]
            if isinstance(existing_pool, list) and existing_pool:
                gif_pool = existing_pool[:GIPHY_FETCH_POOL_SIZE]
            else:
                gif_pool = _dedupe_gif_list(gifs)[:GIPHY_FETCH_POOL_SIZE]
            # #region agent log
            _debug_log("djcap_processor.py:enrich_deck_data", "Reusing existing GIFs", {"gifs_count": len(gifs)}, "J")
            # #endregion
            logger.info(f"Reusing existing GIFs for query='{query}' (count={len(gifs)})")
            should_reuse = True
        else:
            logger.info(f"Not enough GIFs in existing list ({len(gif_only_list)}), will fetch new ones")
    
    if not should_reuse and USE_GIPHY_API and GIPHY_API_KEY and search_keywords:
        try:
            # Try AudioApis first if available, otherwise use direct implementation
            if METADATA_MODULES_AVAILABLE:
                if not _giphy_can_request(cost=len(search_keywords)):
                    logger.warning(
                        f"Giphy rate limit reached ({GIPHY_MAX_REQUESTS_PER_HOUR}/hour). "
                        f"Skipping live Giphy for query={search_keywords} and using offline bank."
                    )
                else:
                    logger.info(f"Fetching GIF pool (limit={per_keyword_limit}) from Giphy via AudioApis for query: {search_keywords[0]}")
                    _giphy_record_request(cost=len(search_keywords))
                    gifs = fetch_gifs_for_keywords(search_keywords, limit_per_keyword=per_keyword_limit)
            else:
                # Use direct Giphy API implementation
                logger.info(f"Fetching GIF pool (limit={per_keyword_limit}) from Giphy API directly for query: {search_keywords[0]}")
                gifs = _fetch_gifs_direct(search_keywords[0], limit=per_keyword_limit)

            # Build pool + select 5 (avoid repeats for same artist)
            gif_pool = _dedupe_gif_list(gifs)[:GIPHY_FETCH_POOL_SIZE]

            # Select up to 5, avoiding recently used GIFs for the same artist.
            gifs = _filter_and_select_gifs_for_artist(artist, gif_pool)
            # #region agent log
            _debug_log("djcap_processor.py:enrich_deck_data", "Giphy API fetch complete", {"gifs_count": len(gifs), "gif_pool_size": len(gif_pool)}, "J")
            # #endregion
            logger.info(f"Giphy API: selected {len(gifs)} GIFs for track (pool={per_keyword_limit})")
            if gifs:
                first = gifs[0]
                logger.info(f"Giphy API: first GIF sample id={first.get('id')}, url={first.get('url')}")
        except Exception as e:
            # #region agent log
            _debug_log("djcap_processor.py:enrich_deck_data", "Giphy API error", {"error": str(e), "error_type": type(e).__name__}, "J")
            # #endregion
            logger.warning(f"Error fetching GIFs from Giphy (will try offline bank if enabled): {e}", exc_info=True)
    else:
        # #region agent log
        _debug_log("djcap_processor.py:enrich_deck_data", "Skipping Giphy API", {"USE_GIPHY_API": USE_GIPHY_API, "METADATA_MODULES_AVAILABLE": METADATA_MODULES_AVAILABLE, "has_api_key": bool(GIPHY_API_KEY), "has_search_keywords": bool(search_keywords)}, "J")
        # #endregion
        logger.debug("Skipping live Giphy API (disabled or no API key)")

    # Offline GIF bank disabled - only use Giphy API
    if not gifs:
        # #region agent log
        _debug_log("djcap_processor.py:enrich_deck_data", "No GIFs fetched from Giphy API", {"search_keywords": search_keywords}, "J")
        # #endregion
        logger.info(f"No GIFs available for keywords: {search_keywords}")
    
    # Get 5 dance videos from offline bank and interleave with GIFs
    dance_videos = get_dance_videos(count=5)
    logger.info(f"Dance video bank: selected {len(dance_videos)} videos")
    
    # Interleave GIFs and videos: GIF, video, GIF, video, etc. (videos on even positions: 2, 4, 6, 8, 10)
    # Ensure we have exactly 5 GIFs and 5 videos for a total of 10 items
    gifs_final = gifs[:5]  # Take first 5 GIFs
    videos_final = dance_videos[:5]  # Take first 5 videos
    
    # Interleave: create list with pattern [GIF, video, GIF, video, ...] (videos on even positions: 2, 4, 6, 8, 10)
    interleaved: List[Dict[str, Any]] = []
    max_len = max(len(gifs_final), len(videos_final))
    for i in range(max_len):
        # Add GIF first (odd positions: 1, 3, 5, 7, 9)
        if i < len(gifs_final):
            interleaved.append(gifs_final[i])
        # Add video second (even positions: 2, 4, 6, 8, 10)
        if i < len(videos_final):
            interleaved.append(videos_final[i])
    
    gifs = interleaved
    logger.info(f"Interleaved media: {len(gifs)} total items ({len(gifs_final)} GIFs + {len(videos_final)} videos)")
    
    # Create enriched deck data - only copy basic fields to avoid recursive structures
    # Do NOT copy current_enriched, next_enriched, or other nested structures
    enriched_deck = {
        'deck': deck_data.get('deck'),
        'title': title,
        'artist': artist,
        'bpm': bpm,
        'key': key,
        'active': True,
        'lastfm_tags': lastfm_tags,
        'refined_keywords': refined_keywords,
        'keyword_scores': keyword_scores,
        'key_characteristics': key_characteristics,
        'gifs': gifs,
        'gif_pool': gif_pool,
        'giphy_query': query,
        'giphy_query_parts': query_parts[:2]
    }
    
    # #region agent log
    _debug_log("djcap_processor.py:enrich_deck_data", "Enrichment complete", {"gifs_count": len(gifs), "gif_pool_size": len(gif_pool), "refined_keywords_count": len(refined_keywords)}, "I")
    # #endregion
    
    return enriched_deck






# Track processing count for periodic cleanup
_process_count = 0

def process_metadata_update(file_path: str):
    """
    Process metadata update when JSON file changes.
    
    Args:
        file_path: Path to the JSON file that changed
    """
    global _last_processed_time, _last_processed_content, _last_active_deck, _last_deck1_active, _last_deck2_active, _process_count
    
    # Debounce: check if we recently processed this file
    current_time = time.time()
    if current_time - _last_processed_time < DEBOUNCE_DELAY:
        return
    
    # Read JSON file
    data = read_djcap_json(file_path)
    if not data:
        logger.warning("Failed to read JSON file")
        return
    
    # Determine current active deck based on active attribute
    deck1_active = data.get('deck1', {}).get('active', False)
    deck2_active = data.get('deck2', {}).get('active', False)
    
    if deck1_active and not deck2_active:
        current_active_deck = 'deck1'
    elif deck2_active and not deck1_active:
        current_active_deck = 'deck2'
    elif deck1_active and deck2_active:
        # Both active - use the one marked as primary_active_deck from metadata_extractor
        current_active_deck = data.get('active_deck', 'deck1')
    else:
        # Fallback to active_deck field if no active attribute is true
        current_active_deck = data.get('active_deck', 'deck1')
    
    # Check if content actually changed OR if active status changed
    # Compare only basic fields (ignore enriched fields that we add)
    basic_data = {
        'deck1': {
            'deck': data.get('deck1', {}).get('deck'),
            'title': data.get('deck1', {}).get('title'),
            'artist': data.get('deck1', {}).get('artist'),
            'bpm': data.get('deck1', {}).get('bpm'),
            'key': data.get('deck1', {}).get('key'),
            'active': data.get('deck1', {}).get('active')
        },
        'deck2': {
            'deck': data.get('deck2', {}).get('deck'),
            'title': data.get('deck2', {}).get('title'),
            'artist': data.get('deck2', {}).get('artist'),
            'bpm': data.get('deck2', {}).get('bpm'),
            'key': data.get('deck2', {}).get('key'),
            'active': data.get('deck2', {}).get('active')
        },
        'active_deck': data.get('active_deck')
    }
    content_str = json.dumps(basic_data, sort_keys=True)
    content_changed = content_str != _last_processed_content
    
    # Check if active status of either deck changed
    deck1_active_changed = deck1_active != _last_deck1_active
    deck2_active_changed = deck2_active != _last_deck2_active
    active_status_changed = deck1_active_changed or deck2_active_changed
    
    # Check if active deck changed
    active_deck_changed = current_active_deck != _last_active_deck
    
    # Also check if active deck doesn't have enriched fields yet
    # OR if enriched fields are stale relative to our current safe GIF policy.
    active_deck_data = data.get(current_active_deck, {})
    if active_deck_data.get('active', False):
        desired_parts = _build_giphy_query_parts(
            active_deck_data.get('title'),
            active_deck_data.get('artist'),
        )

        # Require basic enrichment fields to exist
        has_keywords = bool(active_deck_data.get('refined_keywords'))

        # Enforce our safe policy: never keep MORE than N gifs once we have an artist query.
        # Do not require exactly N (Giphy/offline may return fewer), otherwise we'd loop.
        gifs = active_deck_data.get('gifs')
        gifs_ok = isinstance(gifs, list) and (len(gifs) <= GIPHY_GIFS_PER_TRACK if desired_parts else True)

        # Require query parts to match our intended [title, artist]
        qp = active_deck_data.get('giphy_query_parts')
        qp_ok = (isinstance(qp, list) and qp[:2] == desired_parts) if desired_parts else True

        needs_enrichment = (not has_keywords) or (not gifs_ok) or (not qp_ok)
    else:
        needs_enrichment = False
    
    # Process if content changed OR if active status changed OR if active deck changed OR needs enrichment
    if not content_changed and not active_status_changed and not active_deck_changed and not needs_enrichment:
        logger.debug("Content and active status unchanged, skipping processing")
        return
    
    if needs_enrichment:
        logger.info(f"Active deck '{current_active_deck}' needs enrichment - processing")
    elif active_status_changed:
        logger.info(f"Active status changed - deck1: {_last_deck1_active}→{deck1_active}, deck2: {_last_deck2_active}→{deck2_active} - re-enriching")
    elif active_deck_changed:
        logger.info(f"Active deck changed from '{_last_active_deck}' to '{current_active_deck}' - re-enriching")
    elif content_changed:
        logger.info("Content changed - processing update")
    
    _last_processed_time = current_time
    _last_processed_content = content_str
    _last_active_deck = current_active_deck
    _last_deck1_active = deck1_active
    _last_deck2_active = deck2_active
    
    logger.info("Processing metadata update and enriching active decks...")
    
    # Enrich active decks with transition system
    deck1_data = data.get('deck1', {})
    deck2_data = data.get('deck2', {})
    
    # Helper function to handle transition for a deck
    def process_deck_transition(deck_data, deck_name, is_active):
        if not is_active:
            # Inactive deck - keep only basic metadata
            return {
                'deck': deck_data.get('deck'),
                'title': deck_data.get('title'),
                'artist': deck_data.get('artist'),
                'bpm': deck_data.get('bpm'),
                'key': deck_data.get('key'),
                'active': False
            }
        
        # Active deck - handle transition
        current_enriched = deck_data.get('current_enriched')
        next_enriched = deck_data.get('next_enriched')
        
        # Check if this is a new track (title/artist changed)
        track_id = f"{deck_data.get('title')}|{deck_data.get('artist')}"
        last_track_id = None
        if current_enriched:
            last_track_id = f"{current_enriched.get('title')}|{current_enriched.get('artist')}"
        
        is_new_track = track_id != last_track_id
        
        if is_new_track:
            # New track detected - move current to next, create new current
            logger.info(f"New track detected for {deck_name}: {deck_data.get('title')}")
            
            # Move current to next (for transition)
            if current_enriched:
                deck_data['next_enriched'] = current_enriched.copy()
            
            # Create new enriched data
            new_enriched = enrich_deck_data(deck_data)
            deck_data['current_enriched'] = new_enriched
            
            # Set transition state
            deck_data['transition'] = {
                'in_progress': True,
                'start_time': time.time(),
                'duration': 2.0  # 2 second transition
            }
        else:
            # Same track - update current enriched if needed
            if (
                not current_enriched
                or not current_enriched.get('refined_keywords')
                or _enriched_gif_policy_stale(deck_data, current_enriched)
            ):
                # No current enriched data, create it
                new_enriched = enrich_deck_data(deck_data)
                deck_data['current_enriched'] = new_enriched
            else:
                # Keep existing current enriched
                deck_data['current_enriched'] = current_enriched
            
            # Check if transition is complete
            transition = deck_data.get('transition', {})
            if transition.get('in_progress'):
                elapsed = time.time() - transition.get('start_time', 0)
                if elapsed >= transition.get('duration', 2.0):
                    # Transition complete - clear next
                    deck_data['next_enriched'] = None
                    deck_data['transition'] = {'in_progress': False}
                    logger.info(f"Transition complete for {deck_name}")
        
        # Merge current enriched into main deck data for easy access
        if deck_data.get('current_enriched'):
            current = deck_data['current_enriched']
            deck_data['lastfm_tags'] = current.get('lastfm_tags', [])
            deck_data['refined_keywords'] = current.get('refined_keywords', [])
            deck_data['keyword_scores'] = current.get('keyword_scores', {})
            deck_data['key_characteristics'] = current.get('key_characteristics', [])
            deck_data['gifs'] = current.get('gifs', [])
            deck_data['gif_pool'] = current.get('gif_pool', [])
            deck_data['giphy_query'] = current.get('giphy_query')
            deck_data['giphy_query_parts'] = current.get('giphy_query_parts', [])
            logger.info(
                f"After merge for {deck_name}: gifs={len(deck_data['gifs'])}, "
                f"has_current_enriched={'current_enriched' in deck_data}"
            )
        
        return deck_data
    
    # Process both decks
    if deck1_active:
        logger.info(f"Processing deck1: {deck1_data.get('title')} - {deck1_data.get('artist')}")
        data['deck1'] = process_deck_transition(deck1_data, 'deck1', True)
    else:
        data['deck1'] = process_deck_transition(deck1_data, 'deck1', False)
    
    if deck2_active:
        logger.info(f"Processing deck2: {deck2_data.get('title')} - {deck2_data.get('artist')}")
        data['deck2'] = process_deck_transition(deck2_data, 'deck2', True)
    else:
        data['deck2'] = process_deck_transition(deck2_data, 'deck2', False)
    
    # Update active_deck field
    data['active_deck'] = current_active_deck
    
    # Write enriched data back to djcap_output.json atomically
    try:
        temp_file = f"{file_path}.tmp"
        with open(temp_file, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        Path(temp_file).rename(file_path)
        logger.info("Enriched metadata saved to djcap_output.json")
        
        # Periodic cleanup check
        _process_count += 1
        if _process_count % CLEANUP_CHECK_INTERVAL == 0:
            try:
                cleanup_output_folder(OUTPUT_FOLDER)
            except Exception as e:
                logger.warning(f"Cleanup error (non-fatal): {e}")
    except Exception as e:
        logger.error(f"Failed to save enriched metadata: {e}", exc_info=True)


class DjcapJsonHandler(FileSystemEventHandler):
    """File system event handler for djcap_output.json changes."""

    def _maybe_process(self, path: str, event_name: str):
        """
        Process events that affect the target JSON file.

        Note: `djcap.py` writes atomically (tmp file + rename), which can show up as
        moved/created events rather than a pure "modified" on some platforms/backends.
        """
        if not path:
            return
        if os.path.abspath(path) != os.path.abspath(DJCAP_JSON_FILE):
            return

        logger.info(f"File {event_name} detected: {path}")
        # Small delay to ensure atomic rename/write is complete
        time.sleep(0.1)
        process_metadata_update(DJCAP_JSON_FILE)

    def on_modified(self, event):
        """Handle file modification events."""
        if event.is_directory:
            return
        self._maybe_process(getattr(event, "src_path", None), "modified")

    def on_created(self, event):
        """Handle file creation events (can occur with atomic writes)."""
        if event.is_directory:
            return
        self._maybe_process(getattr(event, "src_path", None), "created")

    def on_moved(self, event):
        """Handle file move/rename events (common for atomic writes: tmp -> final)."""
        if event.is_directory:
            return
        self._maybe_process(getattr(event, "dest_path", None), "moved")


def main():
    """Main function to start the file watcher."""
    global RUNNING
    
    # #region agent log
    _debug_log("djcap_processor.py:main", "Main function entry", {"WATCHDOG_AVAILABLE": WATCHDOG_AVAILABLE, "METADATA_MODULES_AVAILABLE": METADATA_MODULES_AVAILABLE, "USE_GIPHY_API": USE_GIPHY_API, "GIPHY_API_KEY": bool(GIPHY_API_KEY)}, "K")
    # #endregion
    
    if not METADATA_MODULES_AVAILABLE:
        logger.warning("AudioApis metadata modules not available. Some features will be disabled.")
        logger.warning(f"Make sure AudioApis is available at: {AUDIOAPIS_PATH}")
    
    # Register signal handler
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("DjCap Metadata Processor starting...")
    logger.info(f"Watching and enriching: {DJCAP_JSON_FILE}")
    
    # Check if input file exists
    if not os.path.exists(DJCAP_JSON_FILE):
        logger.warning(f"Input file does not exist: {DJCAP_JSON_FILE}")
        logger.info("Waiting for file to be created...")
    
    # Use watchdog if available, otherwise fall back to polling
    if WATCHDOG_AVAILABLE:
        # #region agent log
        _debug_log("djcap_processor.py:main", "Using watchdog file watcher", {}, "K")
        # #endregion
        # Create file watcher
        event_handler = DjcapJsonHandler()
        observer = Observer()
        observer.schedule(event_handler, path=os.path.dirname(DJCAP_JSON_FILE), recursive=False)
        observer.start()
        logger.info("File watcher started (watchdog). Press Ctrl+C to stop.")
    else:
        # #region agent log
        _debug_log("djcap_processor.py:main", "Watchdog not available, using polling fallback", {}, "K")
        # #endregion
        logger.warning("watchdog library not available. Using polling fallback (checking every 2 seconds).")
        logger.warning("For better performance, install watchdog: pip install watchdog")
        observer = None
    
    # Process initial file if it exists
    if os.path.exists(DJCAP_JSON_FILE):
        logger.info("Processing initial file...")
        process_metadata_update(DJCAP_JSON_FILE)
    
    # Keep running
    last_mtime = 0
    try:
        while RUNNING:
            if observer is None:
                # Polling mode: check file modification time
                if os.path.exists(DJCAP_JSON_FILE):
                    current_mtime = os.path.getmtime(DJCAP_JSON_FILE)
                    if current_mtime != last_mtime:
                        # #region agent log
                        _debug_log("djcap_processor.py:main:poll", "File changed detected via polling", {"last_mtime": last_mtime, "current_mtime": current_mtime}, "K")
                        # #endregion
                        last_mtime = current_mtime
                        # Small delay to ensure atomic write is complete
                        time.sleep(0.1)
                        process_metadata_update(DJCAP_JSON_FILE)
            time.sleep(1 if observer else 2)  # Poll every 2 seconds in polling mode
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    finally:
        if observer:
            observer.stop()
            observer.join()
        logger.info("DjCap Metadata Processor stopped.")


if __name__ == "__main__":
    main()

