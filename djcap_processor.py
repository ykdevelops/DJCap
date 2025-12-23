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
import threading

# #region agent log
DEBUG_LOG_PATH = Path(__file__).parent / ".cursor" / "debug.log"
PUBLIC_DEBUG_LOG_PATH = Path(__file__).parent / "data" / "output" / "debug_public.log"
def _debug_log(location, message, data, hypothesis_id):
    try:
        DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        PUBLIC_DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
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
        # Mirror to a non-protected path so the agent can clear it automatically
        try:
            with open(PUBLIC_DEBUG_LOG_PATH, 'a') as f2:
                f2.write(json.dumps(log_entry) + "\n")
        except:
            pass
    except: pass
# #endregion

# Music video state (in-memory)
_music_video_cache: Dict[str, Dict[str, Any]] = {}
_music_video_inflight: set = set()


def _sanitize_music_video_stem(artist: str, title: str) -> str:
    stem = f"{artist} - {title}".strip()
    return stem.replace("/", "_").replace("\\", "_").replace(":", "_")


def _get_cookies_from_browser() -> Optional[str]:
    """
    Try to find an available browser for cookie extraction.
    Returns browser name (e.g., 'chrome', 'safari', 'firefox') or None.
    yt-dlp will auto-detect the browser profile if available.
    """
    import shutil
    import os
    from pathlib import Path
    
    # Priority order: Chrome (most common), Safari, Firefox
    # yt-dlp will handle the actual cookie extraction
    browsers_to_try = ['chrome', 'safari', 'firefox', 'edge', 'brave', 'opera']
    
    for browser in browsers_to_try:
        # Check if browser exists on the system
        if browser == 'safari':
            # Safari cookies are in a system location
            safari_path = Path.home() / "Library" / "Safari"
            if safari_path.exists():
                return 'safari'
        elif browser == 'chrome':
            chrome_path = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
            if chrome_path.exists():
                return 'chrome'
        elif browser == 'firefox':
            firefox_path = Path.home() / "Library" / "Application Support" / "Firefox"
            if firefox_path.exists():
                return 'firefox'
        elif browser == 'edge':
            edge_path = Path.home() / "Library" / "Application Support" / "Microsoft Edge"
            if edge_path.exists():
                return 'edge'
        elif browser == 'brave':
            brave_path = Path.home() / "Library" / "Application Support" / "BraveSoftware" / "Brave-Browser"
            if brave_path.exists():
                return 'brave'
        elif browser == 'opera':
            opera_path = Path.home() / "Library" / "Application Support" / "com.operasoftware.Opera"
            if opera_path.exists():
                return 'opera'
    
    # Fallback: try chrome (most common, yt-dlp will try to find it)
    # Even if path doesn't exist, yt-dlp might still be able to extract cookies
    return 'chrome'


def _download_music_video_full_mp4(title: str, artist: str) -> Optional[Dict[str, Any]]:
    """
    Download a single merged MP4 for the track (equivalent to running yt-dlp in terminal).
    Returns dict with url/mime/title/filename for serving from frontend/server.py.
    """
    try:
        import glob
        import sys as _sys
        import os as _os
        import time as _time
        import subprocess as _subprocess
        import shutil as _shutil
        from urllib.parse import quote as _quote

        # Store videos inside the project so frontend/server.py can serve them
        videos_dir = Path(__file__).parent / "data" / "music_videos"
        videos_dir.mkdir(parents=True, exist_ok=True)

        safe_stem = _sanitize_music_video_stem(artist or "", title or "")
        outtmpl = str(videos_dir / safe_stem) + ".%(ext)s"

        # Prefer Safari-friendly H.264 (avc1) in MP4 when available.
        # This avoids common "black box" playback issues when yt-dlp picks AV1/VP9-in-MP4 formats.
        fmt = 'bv*[ext=mp4][vcodec^=avc1]+ba[ext=m4a]/b[ext=mp4][vcodec^=avc1]/b[ext=mp4]/b'
        query = f"{artist} {title} official music video".strip()
        search_query = f"ytsearch1:{query}"

        def _mp4_is_h264_avc1(path: Path) -> Optional[bool]:
            """
            Best-effort codec check via ffprobe. Returns:
              - True/False if ffprobe available and parsed
              - None if we can't determine
            """
            try:
                ffprobe = _shutil.which("ffprobe")
                if not ffprobe:
                    return None
                cmd = [
                    ffprobe,
                    "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=codec_name,codec_tag_string",
                    "-of", "json",
                    str(path),
                ]
                r = _subprocess.run(cmd, capture_output=True, text=True, timeout=8)
                if r.returncode != 0:
                    return None
                info = json.loads(r.stdout or "{}")
                streams = info.get("streams") or []
                if not streams:
                    return None
                s0 = streams[0] or {}
                codec_name = (s0.get("codec_name") or "").lower()
                codec_tag = (s0.get("codec_tag_string") or "").lower()
                if codec_name == "h264":
                    return True
                if codec_tag.startswith("avc1"):
                    return True
                return False
            except Exception:
                return None

        # FAST PATH: if already downloaded, reuse it immediately
        existing_mp4 = videos_dir / f"{safe_stem}.mp4"
        if existing_mp4.exists() and existing_mp4.is_file():
            compat = _mp4_is_h264_avc1(existing_mp4)
            if compat is False:
                # Known-incompatible codec for Safari; redownload with avc1 preference
                _debug_log(
                    "djcap_processor.py:_download_music_video_full_mp4:cache",
                    "cache_incompatible_redownload",
                    {"filename": existing_mp4.name, "size_bytes": existing_mp4.stat().st_size},
                    "MV-FULL-CACHE",
                )
                try:
                    existing_mp4.unlink()
                except Exception:
                    pass
            else:
            # #region agent log
                _debug_log(
                    "djcap_processor.py:_download_music_video_full_mp4:cache",
                    "cache_hit",
                    {"filename": existing_mp4.name, "size_bytes": existing_mp4.stat().st_size, "h264_avc1": compat},
                    "MV-FULL-CACHE",
                )
            # #endregion
                return {
                    "id": f"music_full_{existing_mp4.stem}",
                    "url": f"/api/music_video/{_quote(existing_mp4.name)}",
                    "title": f"{artist} - {title}",
                    "mime": "video/mp4",
                    "filename": existing_mp4.name,
                }

        yt_dlp_bin = _shutil.which("yt-dlp") or _shutil.which("yt_dlp")

        # #region agent log
        _debug_log(
            "djcap_processor.py:_download_music_video_full_mp4:entry",
            "enter",
            {
                "title": title,
                "artist": artist,
                "search_query": search_query,
                "outtmpl": outtmpl,
                "format": fmt,
                "py_executable": getattr(_sys, "executable", None),
                "cwd": _os.getcwd(),
                "yt_dlp_bin": yt_dlp_bin,
            },
            "MV-FULL-A",
        )
        # #endregion

        if not yt_dlp_bin:
            # #region agent log
            _debug_log(
                "djcap_processor.py:_download_music_video_full_mp4",
                "no_yt_dlp_binary",
                {"path_head": (_os.environ.get("PATH") or "")[:180]},
                "MV-FULL-Z",
            )
            # #endregion
            return None

        # Add cookie support to bypass YouTube bot detection
        browser = _get_cookies_from_browser()
        cmd = [
            yt_dlp_bin,
            "-f", fmt,
            "--merge-output-format", "mp4",
            "--no-playlist",
            "-o", outtmpl,
        ]
        
        # Add cookies if browser is available (helps bypass YouTube bot detection)
        if browser:
            cmd.extend(["--cookies-from-browser", browser])
            # #region agent log
            _debug_log(
                "djcap_processor.py:_download_music_video_full_mp4:cookies",
                "using_browser_cookies",
                {"browser": browser},
                "MV-FULL-COOKIES",
            )
            # #endregion
        
        cmd.append(search_query)

        t0 = _time.time()
        proc = _subprocess.run(cmd, capture_output=True, text=True)
        t1 = _time.time()

        # #region agent log
        _debug_log(
            "djcap_processor.py:_download_music_video_full_mp4:cli",
            "yt_dlp_finished",
            {
                "returncode": proc.returncode,
                "elapsed_s": round(t1 - t0, 2),
                "stdout_tail": (proc.stdout or "")[-800:],
                "stderr_tail": (proc.stderr or "")[-800:],
                "has_cookies": bool(browser),
            },
            "MV-FULL-B",
        )
        # #endregion

        if proc.returncode != 0:
            # Check if it's a bot detection error
            stderr_lower = (proc.stderr or "").lower()
            if "bot" in stderr_lower or "sign in" in stderr_lower or "cookies" in stderr_lower:
                # #region agent log
                _debug_log(
                    "djcap_processor.py:_download_music_video_full_mp4:error",
                    "youtube_bot_detection",
                    {
                        "title": title,
                        "artist": artist,
                        "browser_used": browser,
                        "stderr_preview": (proc.stderr or "")[:500],
                    },
                    "MV-FULL-ERROR",
                )
                # #endregion
            return None

        candidates = sorted(glob.glob(str(videos_dir / (safe_stem + ".*"))))
        mp4 = next((c for c in candidates if c.lower().endswith(".mp4")), None)
        chosen = mp4 or (candidates[-1] if candidates else None)

        # #region agent log
        _debug_log(
            "djcap_processor.py:_download_music_video_full_mp4:download",
            "download_done",
            {
                "candidates": [Path(c).name for c in candidates][-10:],
                "chosen": Path(chosen).name if chosen else None,
            },
            "MV-FULL-C",
        )
        # #endregion

        if not chosen:
            return None

        chosen_path = Path(chosen)
        return {
            "id": f"music_full_{chosen_path.stem}",
            "url": f"/api/music_video/{_quote(chosen_path.name)}",
            "title": f"{artist} - {title}",
            "mime": "video/mp4",
            "filename": chosen_path.name,
        }
    except Exception as e:
        # #region agent log
        import traceback as _tb
        _debug_log(
            "djcap_processor.py:_download_music_video_full_mp4",
            "exception",
            {"error_type": type(e).__name__, "error": str(e)[:300], "traceback": _tb.format_exc()[-1200:]},
            "MV-FULL-Z",
        )
        # #endregion
        return None


def _maybe_start_music_video_download(track_id: str, title: str, artist: str, bpm: float) -> None:
    """
    Start a background yt-dlp download + precut for a track if we don't already have clips.
    Uses in-memory cache + inflight guard to avoid repeated downloads.
    """
    # #region agent log
    _debug_log(
        "djcap_processor.py:_maybe_start_music_video_download",
        "function_entry",
        {
            "track_id": track_id,
            "title": title,
            "artist": artist,
            "bpm": bpm,
            "has_track_id": bool(track_id),
            "has_title": bool(title),
            "has_artist": bool(artist),
            "has_bpm": bool(bpm),
        },
        "MV-DEBUG-3",
    )
    # #endregion
    try:
        if not track_id or not title or not artist or not bpm:
            # #region agent log
            _debug_log(
                "djcap_processor.py:_maybe_start_music_video_download",
                "skip_missing_fields",
                {"track_id": track_id, "has_title": bool(title), "has_artist": bool(artist), "bpm": bpm},
                "MV-H",
            )
            # #endregion
            return

        # #region agent log
        _debug_log(
            "djcap_processor.py:_maybe_start_music_video_download",
            "checking_cache",
            {
                "track_id": track_id,
                "in_cache": track_id in _music_video_cache,
                "in_inflight": track_id in _music_video_inflight,
            },
            "MV-DEBUG-4",
        )
        # #endregion
        
        if track_id in _music_video_cache:
            cached = _music_video_cache.get(track_id) or {}
            # Allow retry if we previously failed/emptied (e.g., missing yt-dlp module/binary)
            status = cached.get("status")
            downloaded_at = cached.get("downloaded_at") or 0
            time_since_download = time.time() - float(downloaded_at or 0) if downloaded_at else 0
            # #region agent log
            _debug_log(
                "djcap_processor.py:_maybe_start_music_video_download",
                "cache_check_details",
                {
                    "track_id": track_id,
                    "status": status,
                    "downloaded_at": downloaded_at,
                    "time_since_download": time_since_download,
                    "should_retry": status in {"error", "empty"} and time_since_download > 10,
                },
                "MV-DEBUG-5",
            )
            # #endregion
            # Retry if status is "error" or "empty" and it's been more than 10 seconds
            # Also retry "empty" status immediately if it was from a missing module (likely yt_dlp wasn't installed)
            should_retry = False
            if status in {"error", "empty"}:
                if time_since_download > 10:
                    should_retry = True
                elif status == "empty" and time_since_download > 0:
                    # For "empty" status, retry after 30 seconds to allow time for yt_dlp installation
                    should_retry = time_since_download > 30
            
            if should_retry:
                try:
                    _music_video_cache.pop(track_id, None)
                except Exception:
                    pass
                # #region agent log
                _debug_log(
                    "djcap_processor.py:_maybe_start_music_video_download",
                    "retry_after_cached_failure",
                    {"track_id": track_id, "status": status, "downloaded_at": downloaded_at},
                    "MV-H",
                )
                # #endregion
            else:
                # #region agent log
                _debug_log(
                    "djcap_processor.py:_maybe_start_music_video_download",
                    "skip_cached",
                    {
                        "track_id": track_id,
                        "status": status,
                        "downloaded_at": downloaded_at,
                        "clips_count": len(_music_video_cache.get(track_id, {}).get("clips") or []),
                        "has_video": bool((_music_video_cache.get(track_id, {}) or {}).get("video")),
                    },
                    "MV-H",
                )
                # #endregion
                return

        if track_id in _music_video_inflight:
            # #region agent log
            _debug_log(
                "djcap_processor.py:_maybe_start_music_video_download",
                "skip_inflight",
                {"track_id": track_id},
                "MV-H",
            )
            # #endregion
            return

        _music_video_inflight.add(track_id)
        started_at = time.time()
        # #region agent log
        _debug_log(
            "djcap_processor.py:_maybe_start_music_video_download",
            "start_thread",
            {"track_id": track_id, "title": title, "artist": artist, "bpm": bpm},
            "MV-H",
        )
        # #endregion

        def _worker():
            # #region agent log
            _debug_log(
                "djcap_processor.py:_maybe_start_music_video_download:worker",
                "worker_started",
                {
                    "track_id": track_id,
                    "title": title,
                    "artist": artist,
                    "bpm": bpm,
                    "mode": MUSIC_VIDEO_DOWNLOAD_MODE,
                },
                "MV-DEBUG-6",
            )
            # #endregion
            try:
                if MUSIC_VIDEO_DOWNLOAD_MODE == "precut":
                    # #region agent log
                    _debug_log(
                        "djcap_processor.py:_maybe_start_music_video_download:worker",
                        "calling_precut",
                        {"track_id": track_id},
                        "MV-DEBUG-7",
                    )
                    # #endregion
                    clips = _download_and_precut_music_video(title, artist, bpm)
                    _music_video_cache[track_id] = {
                        "status": "ready" if clips else "empty",
                        "clips": clips,
                        "video": None,
                        "downloaded_at": time.time(),
                        "started_at": started_at,
                    }
                else:
                    # #region agent log
                    _debug_log(
                        "djcap_processor.py:_maybe_start_music_video_download:worker",
                        "calling_full_mp4",
                        {"track_id": track_id},
                        "MV-DEBUG-8",
                    )
                    # #endregion
                    video = _download_music_video_full_mp4(title, artist)
                    _music_video_cache[track_id] = {
                        "status": "ready" if video else "empty",
                        "clips": [],
                        "video": video,
                        "downloaded_at": time.time(),
                        "started_at": started_at,
                    }
                # #region agent log
                _debug_log(
                    "djcap_processor.py:_maybe_start_music_video_download:worker",
                    "worker_done",
                    {
                        "track_id": track_id,
                        "status": _music_video_cache[track_id]["status"],
                        "clips_count": len(_music_video_cache[track_id].get("clips") or []),
                        "has_video": bool(_music_video_cache[track_id].get("video")),
                        "elapsed_s": round(time.time() - started_at, 2),
                    },
                    "MV-I",
                )
                # #endregion
            except Exception as e:
                _music_video_cache[track_id] = {
                    "status": "error",
                    "clips": [],
                    "video": None,
                    "downloaded_at": time.time(),
                    "started_at": started_at,
                    "error": str(e)[:300],
                }
                # #region agent log
                _debug_log(
                    "djcap_processor.py:_maybe_start_music_video_download:worker",
                    "worker_exception",
                    {"track_id": track_id, "error_type": type(e).__name__, "error": str(e)[:300]},
                    "MV-I",
                )
                # #endregion
            finally:
                try:
                    _music_video_inflight.discard(track_id)
                except Exception:
                    pass

        # #region agent log
        _debug_log(
            "djcap_processor.py:_maybe_start_music_video_download",
            "starting_thread",
            {
                "track_id": track_id,
                "thread_started": True,
            },
            "MV-DEBUG-9",
        )
        # #endregion
        threading.Thread(target=_worker, daemon=True).start()
    except Exception as e:
        # #region agent log
        _debug_log(
            "djcap_processor.py:_maybe_start_music_video_download",
            "outer_exception",
            {"error_type": type(e).__name__, "error": str(e)[:300]},
            "MV-H",
        )
        # #endregion
        return

# Load API keys early (loads repo-root `.env` via python-dotenv).
# Important: AudioApis `metadata.giphy_client` imports its own `config` module and reads
# `GIPHY_API_KEY` at import time. If we import AudioApis first, it can cache an empty key.
from src.config import LASTFM_API_KEY, GIPHY_API_KEY, GOOGLE_API_KEY, GOOGLE_CSE_ID

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

# Direct Google Custom Search API implementation for GIFs
def _fetch_gifs_from_google(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Fetch GIFs from Google Custom Search API using artist name.
    Returns list of GIF dicts with id, url, title, tags, etc.
    """
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID or not query:
        # #region agent log
        _debug_log(
            "djcap_processor.py:_fetch_gifs_from_google",
            "skip_missing_config_or_query",
            {"has_google_api_key": bool(GOOGLE_API_KEY), "has_google_cse_id": bool(GOOGLE_CSE_ID), "has_query": bool(query)},
            "GIF-H1",
        )
        # #endregion
        return []
    
    try:
        import urllib.request
        import urllib.parse
        
        # Google Custom Search API endpoint
        base_url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "q": query,
            "cx": GOOGLE_CSE_ID,
            "key": GOOGLE_API_KEY,
            "searchType": "image",
            "imgType": "animated",  # Filter for animated images (GIFs)
            "num": min(limit, 10),  # Google max is 10 per request
            "safe": "active"  # Safe search
        }
        
        url = f"{base_url}?{urllib.parse.urlencode(params)}"
        
        # #region agent log
        _debug_log("djcap_processor.py:_fetch_gifs_from_google", "Fetching from Google API", {"query": query, "limit": limit, "url": url.replace(GOOGLE_API_KEY, "***").replace(GOOGLE_CSE_ID, "***")}, "J")
        # #endregion
        
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())
            
        gifs = []
        items = data.get("items", [])
        for item in items[:limit]:
            # Extract image URL - prefer the link, fallback to image object
            image_url = item.get("link") or item.get("image", {}).get("url") or ""
            if not image_url:
                continue
                
            gif = {
                "id": f"google_{item.get('link', '').split('/')[-1]}" or f"google_{hash(image_url) % 1000000}",
                "url": image_url,
                "title": item.get("title", ""),
                "rating": "g",  # Google safe search ensures this
                "source": "google",
                "width": item.get("image", {}).get("width") or 480,
                "height": item.get("image", {}).get("height") or 270,
                "tags": []  # Google doesn't provide tags
            }
            if gif["url"]:  # Only add if we have a valid URL
                gifs.append(gif)
        
        # #region agent log
        _debug_log("djcap_processor.py:_fetch_gifs_from_google", "Google API response", {"gifs_count": len(gifs)}, "J")
        # #endregion
        
        return gifs
    except Exception as e:
        # #region agent log
        _debug_log("djcap_processor.py:_fetch_gifs_from_google", "Google API error", {"error": str(e), "error_type": type(e).__name__}, "J")
        # #endregion
        logger.warning(f"Error fetching GIFs from Google: {e}")
        return []

# Direct Giphy API implementation (fallback when AudioApis not available)
def _fetch_gifs_direct(query: str, limit: int = 25) -> List[Dict[str, Any]]:
    """
    Direct Giphy API implementation that doesn't require AudioApis.
    Returns list of GIF dicts with id, url, title, tags, etc.
    """
    if not GIPHY_API_KEY or not query:
        # #region agent log
        _debug_log(
            "djcap_processor.py:_fetch_gifs_direct",
            "skip_missing_config_or_query",
            {"has_giphy_api_key": bool(GIPHY_API_KEY), "has_query": bool(query)},
            "GIF-H1",
        )
        # #endregion
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
import threading

# Configuration: Set to False to skip API calls entirely (faster, no external dependencies)
USE_LASTFM_API = False  # Set to False to skip Last.fm API calls
USE_GIPHY_API = True   # Enable live Giphy API calls for GIF fetching
USE_KEYWORD_ANALYZER = False  # Set to False to skip keyword analyzer (use basic keywords: title, artist, key characteristics)

# Music video behavior
# Keep this False until we explicitly want music video clips mixed into the main visuals rotation.
USE_MUSIC_VIDEO_IN_VISUALS_ROTATION = True
# Download mode: "full" downloads a single merged MP4 (terminal-like). "precut" creates many clips.
MUSIC_VIDEO_DOWNLOAD_MODE = "full"

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
    max_count: int = GIPHY_GIFS_PER_TRACK,
) -> List[Dict[str, Any]]:
    """
    Prefer GIFs not recently used for the same artist.
    Returns <= max_count (defaults to GIPHY_GIFS_PER_TRACK) and records selections to history.
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

    selected = (fresh + fallback)[:max_count]

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


def _create_music_video_clip_dicts(clips_dir: Path, clip_paths: List[Path], artist: str, title: str) -> List[Dict[str, Any]]:
    """Create video dicts in the same format as dance videos."""
    result = []
    for clip_path in clip_paths:
        # Create relative path for URL (from data/ directory)
        relative_path = clip_path.relative_to(clips_dir.parent.parent)
        
        video_dict = {
            "id": f"music_{clip_path.stem}",
            "url": f"/api/music_video_clip/{relative_path.as_posix()}",
            "title": f"{artist} - {title} (Clip {clip_path.stem})",
            "mime": "video/mp4",
            "source": "music_video",
            "width": 480,
            "height": 270,
            "tags": [artist.lower(), title.lower(), "music_video"]
        }
        result.append(video_dict)
    
    return result


def _download_and_precut_music_video(title: str, artist: str, bpm: float) -> List[Dict[str, Any]]:
    """
    Download music video and precut it into 2-beat clips matching the BPM.
    
    Args:
        title: Song title
        artist: Artist name
        bpm: Beats per minute for the track
        
    Returns:
        List of video clip dicts (same format as dance videos)
    """
    try:
        # Check if yt_dlp is available before attempting download
        try:
            import yt_dlp
        except ImportError:
            logger.warning("yt_dlp module not installed. Install it with: pip install yt-dlp")
            # #region agent log
            _debug_log(
                "djcap_processor.py:_download_and_precut_music_video",
                "yt_dlp_missing",
                {"title": title, "artist": artist, "bpm": bpm},
                "MV-DEBUG-YTDLP",
            )
            # #endregion
            return []
        
        import subprocess
        from pathlib import Path
        import shutil
        import traceback
        import sys as _sys
        import os as _os

        # #region agent log
        _debug_log(
            "djcap_processor.py:_download_and_precut_music_video:entry",
            "enter",
            {
                "title": title,
                "artist": artist,
                "bpm": bpm,
                "py_executable": getattr(_sys, "executable", None),
                "py_version": getattr(_sys, "version", "")[:80],
                "cwd": _os.getcwd(),
                "has_ffmpeg": bool(shutil.which("ffmpeg")),
                "has_ffprobe": bool(shutil.which("ffprobe")),
                "path_head": (_os.environ.get("PATH") or "")[:160],
                "yt_dlp_version": getattr(yt_dlp, "__version__", None),
            },
            "MV-A",
        )
        # #endregion
        
        # Create directories
        # Store videos inside the project so frontend/server.py can serve them
        videos_dir = Path(__file__).parent / "data" / "music_videos"
        # Sanitize folder name
        safe_folder_name = f"{artist} - {title}".replace("/", "_").replace("\\", "_").replace(":", "_")
        clips_dir = videos_dir / safe_folder_name
        clips_dir.mkdir(parents=True, exist_ok=True)
        
        # Check if already processed
        existing_clips = sorted(list(clips_dir.glob("clip_*.mp4")))
        if existing_clips:
            logger.info(f"Found {len(existing_clips)} existing clips for {artist} - {title}")
            return _create_music_video_clip_dicts(clips_dir, existing_clips, artist, title)
        
        # Download full video
        query = f"{artist} {title} official music video"
        temp_video_name = f"temp_{safe_folder_name}"
        temp_video = videos_dir / temp_video_name
        
        # Add cookie support to bypass YouTube bot detection
        browser = _get_cookies_from_browser()
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': str(temp_video) + '.%(ext)s',
            'quiet': False,
            'no_warnings': False,
        }
        
        # Add cookies if browser is available (helps bypass YouTube bot detection)
        if browser:
            ydl_opts['cookiefrombrowser'] = (browser,)
            # #region agent log
            _debug_log(
                "djcap_processor.py:_download_and_precut_music_video:cookies",
                "using_browser_cookies",
                {"browser": browser},
                "MV-PRECUT-COOKIES",
            )
            # #endregion
        
        logger.info(f"Searching for music video: {artist} - {title}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Use ytsearch1: prefix to search YouTube and download first result
            try:
                search_query = f"ytsearch1:{query}"
                _t_download_start = time.time()
                # #region agent log
                _debug_log(
                    "djcap_processor.py:_download_and_precut_music_video:yt_dlp",
                    "about_to_download",
                    {
                        "search_query": search_query,
                        "outtmpl": ydl_opts.get("outtmpl"),
                        "format": ydl_opts.get("format"),
                    },
                    "MV-B",
                )
                # #endregion
                logger.info(f"Using search query: {search_query}")
                ydl.download([search_query])
                _t_download_end = time.time()
                # #region agent log
                try:
                    temp_candidates = sorted([p.name for p in videos_dir.glob(f"{temp_video_name}.*")])
                except Exception:
                    temp_candidates = ["<glob_failed>"]
                _debug_log(
                    "djcap_processor.py:_download_and_precut_music_video:yt_dlp",
                    "download_returned",
                    {
                        "temp_candidates": temp_candidates[:20],
                        "clips_dir_exists": clips_dir.exists(),
                        "clips_dir_files": len(list(clips_dir.glob("*"))) if clips_dir.exists() else 0,
                        "download_elapsed_s": round(_t_download_end - _t_download_start, 2),
                    },
                    "MV-B",
                )
                # #endregion
                logger.info(f"Download completed for: {artist} - {title}")
            except Exception as e:
                logger.error(f"Error downloading video with ytsearch1: {e}")
                # #region agent log
                _debug_log(
                    "djcap_processor.py:_download_and_precut_music_video:yt_dlp",
                    "download_exception_primary",
                    {
                        "error_type": type(e).__name__,
                        "error": str(e)[:300],
                        "traceback": traceback.format_exc()[-1200:],
                    },
                    "MV-C",
                )
                # #endregion
                # Try alternative: extract info first, then download
                try:
                    logger.info(f"Trying alternative download method...")
                    info = ydl.extract_info(f"ytsearch1:{query}", download=False)
                    if info and 'entries' in info and len(info['entries']) > 0:
                        video_url = info['entries'][0]['webpage_url']
                        video_title = info['entries'][0].get('title', 'Unknown')
                        logger.info(f"Found video: {video_title} - {video_url}")
                        _t_download_start = time.time()
                        ydl.download([video_url])
                        _t_download_end = time.time()
                        # #region agent log
                        try:
                            temp_candidates = sorted([p.name for p in videos_dir.glob(f"{temp_video_name}.*")])
                        except Exception:
                            temp_candidates = ["<glob_failed>"]
                        _debug_log(
                            "djcap_processor.py:_download_and_precut_music_video:yt_dlp",
                            "download_returned_fallback",
                            {
                                "video_title": str(video_title)[:120],
                                "temp_candidates": temp_candidates[:20],
                                "download_elapsed_s": round(_t_download_end - _t_download_start, 2),
                            },
                            "MV-C",
                        )
                        # #endregion
                        logger.info(f"Download completed via alternative method")
                    else:
                        logger.warning(f"No video found for: {query}")
                        return []
                except Exception as e2:
                    logger.error(f"Alternative download method also failed: {e2}", exc_info=True)
                    # #region agent log
                    _debug_log(
                        "djcap_processor.py:_download_and_precut_music_video:yt_dlp",
                        "download_exception_fallback",
                        {
                            "error_type": type(e2).__name__,
                            "error": str(e2)[:300],
                            "traceback": traceback.format_exc()[-1200:],
                        },
                        "MV-C",
                    )
                    # #endregion
                    return []
        
        # Find downloaded file
        downloaded_file = None
        for ext in ['.mp4', '.mkv', '.webm', '.m4a']:
            candidate = temp_video.with_suffix(ext)
            if candidate.exists():
                downloaded_file = candidate
                break
        
        if not downloaded_file:
            logger.warning(f"Downloaded video file not found for {artist} - {title}")
            # #region agent log
            try:
                temp_candidates = sorted([p.name for p in videos_dir.glob(f"{temp_video_name}.*")])
            except Exception:
                temp_candidates = ["<glob_failed>"]
            _debug_log(
                "djcap_processor.py:_download_and_precut_music_video:file_detect",
                "downloaded_file_not_found",
                {
                    "expected_prefix": str(temp_video),
                    "temp_candidates": temp_candidates[:30],
                },
                "MV-D",
            )
            # #endregion
            return []
        
        # Get video duration using ffprobe
        try:
            _t_ffprobe_start = time.time()
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(downloaded_file)],
                capture_output=True,
                text=True,
                timeout=10
            )
            _t_ffprobe_end = time.time()
            # #region agent log
            _debug_log(
                "djcap_processor.py:_download_and_precut_music_video:ffprobe",
                "ffprobe_done",
                {
                    "returncode": result.returncode,
                    "stdout": (result.stdout or "")[:200],
                    "stderr": (result.stderr or "")[:200],
                    "downloaded_file": downloaded_file.name,
                    "ffprobe_elapsed_s": round(_t_ffprobe_end - _t_ffprobe_start, 2),
                },
                "MV-E",
            )
            # #endregion
            duration = float(result.stdout.strip())
        except Exception as e:
            logger.warning(f"Could not get video duration: {e}, using default 180s")
            # #region agent log
            _debug_log(
                "djcap_processor.py:_download_and_precut_music_video:ffprobe",
                "ffprobe_exception",
                {
                    "error_type": type(e).__name__,
                    "error": str(e)[:300],
                    "traceback": traceback.format_exc()[-1200:],
                },
                "MV-E",
            )
            # #endregion
            duration = 180.0  # Default 3 minutes
        
        # Calculate clip duration (1 second fixed)
        clip_duration = 1.0  # Fixed 1 second per clip
        
        # Precut into clips (limit to reasonable number)
        clip_count = min(int(duration / clip_duration), 50)  # Max 50 clips
        clips = []
        _t_cut_start = time.time()
        
        logger.info(f"Precutting {duration:.1f}s video into {clip_count} clips of {clip_duration:.2f}s each (BPM: {bpm})")
        
        for i in range(clip_count):
            start_time = i * clip_duration
            clip_path = clips_dir / f"clip_{i:04d}.mp4"
            
            # Use ffmpeg to extract clip
            try:
                if i == 0:
                    # #region agent log
                    _debug_log(
                        "djcap_processor.py:_download_and_precut_music_video:ffmpeg",
                        "cutting_first_clip",
                        {
                            "start_time": start_time,
                            "clip_duration": clip_duration,
                            "downloaded_file": downloaded_file.name,
                            "clip_path": str(clip_path),
                            "planned_clip_count": clip_count,
                        },
                        "MV-F",
                    )
                    # #endregion
                # Add fade in (0.1s) and fade out (0.1s) effects
                # Total clip is 1.0s, with 0.1s fade in at start and 0.1s fade out at end
                fade_duration = 0.1  # 100ms fade in/out
                subprocess.run(
                    ['ffmpeg', '-i', str(downloaded_file), '-ss', str(start_time), '-t', str(clip_duration),
                     '-vf', f'fade=t=in:st=0:d={fade_duration},fade=t=out:st={clip_duration - fade_duration}:d={fade_duration}',
                     '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', '-y', str(clip_path)],
                    capture_output=True,
                    timeout=30,
                    check=True
                )
                clips.append(clip_path)
            except subprocess.TimeoutExpired:
                logger.warning(f"Timeout cutting clip {i} for {artist} - {title}")
                # #region agent log
                _debug_log(
                    "djcap_processor.py:_download_and_precut_music_video:ffmpeg",
                    "ffmpeg_timeout",
                    {"clip_index": i, "start_time": start_time, "clip_duration": clip_duration},
                    "MV-F",
                )
                # #endregion
                break
            except subprocess.CalledProcessError as e:
                logger.warning(f"Error cutting clip {i} for {artist} - {title}: {e}")
                # #region agent log
                stderr = ""
                try:
                    stderr = (e.stderr.decode("utf-8", errors="ignore") if isinstance(e.stderr, (bytes, bytearray)) else str(e.stderr or ""))[:300]
                except Exception:
                    stderr = "<stderr_decode_failed>"
                _debug_log(
                    "djcap_processor.py:_download_and_precut_music_video:ffmpeg",
                    "ffmpeg_calledprocesserror",
                    {
                        "clip_index": i,
                        "returncode": getattr(e, "returncode", None),
                        "stderr": stderr,
                    },
                    "MV-F",
                )
                # #endregion
                break
        _t_cut_end = time.time()
        
        # Clean up temp file
        try:
            downloaded_file.unlink()
        except Exception:
            pass
        
        if clips:
            logger.info(f"Created {len(clips)} clips for {artist} - {title}")
            # #region agent log
            _debug_log(
                "djcap_processor.py:_download_and_precut_music_video:exit",
                "success",
                {
                    "clips_count": len(clips),
                    "clips_dir": str(clips_dir),
                    "cut_elapsed_s": round(_t_cut_end - _t_cut_start, 2),
                },
                "MV-G",
            )
            # #endregion
            return _create_music_video_clip_dicts(clips_dir, clips, artist, title)
        else:
            logger.warning(f"No clips created for {artist} - {title}")
            # #region agent log
            _debug_log(
                "djcap_processor.py:_download_and_precut_music_video:exit",
                "no_clips",
                {
                    "clips_count": 0,
                    "clips_dir": str(clips_dir),
                    "cut_elapsed_s": round(_t_cut_end - _t_cut_start, 2),
                },
                "MV-G",
            )
            # #endregion
            return []
        
    except Exception as e:
        logger.warning(f"Failed to download/precut music video for {artist} - {title}: {e}", exc_info=True)
        # #region agent log
        try:
            import traceback as _tb
            tb = _tb.format_exc()[-1200:]
        except Exception:
            tb = "<traceback_unavailable>"
        _debug_log(
            "djcap_processor.py:_download_and_precut_music_video:outer",
            "outer_exception",
            {"error_type": type(e).__name__, "error": str(e)[:300], "traceback": tb},
            "MV-Z",
        )
        # #endregion
        return []


def _cleanup_old_music_videos(data: Dict[str, Any]) -> None:
    """
    Clean up music video clips for tracks that have been inactive for more than 1 minute.
    """
    try:
        from pathlib import Path
        import shutil
        
        # Store videos inside the project so frontend/server.py can serve them
        videos_dir = Path(__file__).parent / "data" / "music_videos"
        if not videos_dir.exists():
            return
        
        current_time = time.time()
        
        # Check both decks
        for deck_name in ['deck1', 'deck2']:
            deck_data = data.get(deck_name, {})
            current_enriched = deck_data.get('current_enriched', {})
            
            # Get download time
            downloaded_at = current_enriched.get('music_video_downloaded_at', 0)
            
            if downloaded_at:
                # Check if deck is inactive
                is_active = deck_data.get('active', False)
                
                if not is_active:
                    # Check if it's been inactive for more than 1 minute
                    time_since_download = current_time - downloaded_at
                    if time_since_download > MUSIC_VIDEO_CLEANUP_THRESHOLD:
                        # Delete either precut directory or full MP4, depending on what's stored
                        mv = current_enriched.get("music_video") or deck_data.get("music_video") or {}
                        filename = mv.get("filename")
                        if filename and isinstance(filename, str):
                            file_path = videos_dir / filename
                            if file_path.exists() and file_path.is_file():
                                try:
                                    file_path.unlink()
                                    logger.info(f"Cleaned up music video file: {file_path}")
                                except Exception as e:
                                    logger.warning(f"Failed to delete music video file {file_path}: {e}")
                        else:
                            # Fallback: remove precut folder convention
                            title = deck_data.get('title', '')
                            artist = deck_data.get('artist', '')
                            if title and artist:
                                safe_folder_name = f"{artist} - {title}".replace("/", "_").replace("\\", "_").replace(":", "_")
                                clips_dir = videos_dir / safe_folder_name
                                if clips_dir.exists() and clips_dir.is_dir():
                                    try:
                                        shutil.rmtree(clips_dir)
                                        logger.info(f"Cleaned up music video clips: {clips_dir}")
                                    except Exception as e:
                                        logger.warning(f"Failed to delete music video clips {clips_dir}: {e}")
                        
    except Exception as e:
        logger.warning(f"Error during music video cleanup: {e}")


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
MUSIC_VIDEO_CLEANUP_THRESHOLD = 60  # Delete clips 1 minute after track becomes inactive

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
    
    # DISABLED: GIPHY and Google videos - only use bank MP4s and music videos
    logger.info("GIPHY and Google videos disabled - using only bank MP4s and music videos")
    gifs: List[Dict[str, Any]] = []
    gif_pool: List[Dict[str, Any]] = []
    google_gifs: List[Dict[str, Any]] = []
    google_query_parts: List[str] = []
    
    # Show music video with dance video overlays every other second
    logger.info("Visuals mode: music video with dance video overlays")
    
    # Set gifs to empty list so only music video is shown in main rotation
    gifs = []
    
    # Get dance videos for overlay (separate from main rotation)
    from src.dance_video_bank import get_dance_videos
    # Request more videos to get good variety (each video creates 3 clips, so 20 videos = 60 clips, but we limit to 20)
    dance_videos_for_overlay = get_dance_videos(count=60)  # Get many clips for variety
    logger.info(f"Dance video overlay: {len(dance_videos_for_overlay)} video clips available for overlay")
    if dance_videos_for_overlay:
        logger.info(f"Sample overlay video URL: {dance_videos_for_overlay[0].get('url', 'no url')}")
    
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
        'giphy_query': None,  # Disabled
        'giphy_query_parts': [],  # Disabled
        'google_query_parts': [],  # Disabled
        'refined_keywords': refined_keywords,
        'keyword_scores': keyword_scores,
        'key_characteristics': key_characteristics,
        'gifs': gifs,
        'gif_pool': gif_pool,
        'dance_videos_overlay': dance_videos_for_overlay  # Dance videos for overlay
    }
    
    logger.debug(f"Enriched deck includes google_query_parts: {'google_query_parts' in enriched_deck}, value: {enriched_deck.get('google_query_parts')}")
    
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
    
    # #region agent log
    _debug_log("djcap_processor.py:process_metadata_update", "Content change check", {
        "content_changed": content_changed,
        "deck1_title": basic_data['deck1'].get('title'),
        "deck1_artist": basic_data['deck1'].get('artist'),
        "deck1_active": basic_data['deck1'].get('active'),
        "deck2_title": basic_data['deck2'].get('title'),
        "deck2_artist": basic_data['deck2'].get('artist'),
        "deck2_active": basic_data['deck2'].get('active'),
        "active_deck": basic_data.get('active_deck'),
        "has_last_content": bool(_last_processed_content)
    }, "K")
    # #endregion
    
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
        # IMPORTANT: `deck.gifs` is the final interleaved visuals list (typically 15 items),
        # not the raw "Giphy-only" list. The previous check compared the total interleaved
        # list length against `GIPHY_GIFS_PER_TRACK` (5), which caused perpetual enrichment
        # and API spam (Google 429 / Giphy throttling).
        gifs = active_deck_data.get('gifs')
        if isinstance(gifs, list):
            total_items = len(gifs)
            # Count only non-video media (best-effort)
            non_video = [
                g for g in gifs
                if isinstance(g, dict)
                and (str(g.get("mime") or "").lower() != "video/mp4")
                and (str(g.get("source") or "") != "dance_mp4_bank")
                and (not str(g.get("url") or "").lower().endswith(".mp4"))
            ]
            gifs_ok = total_items > 0
            non_video_count = len(non_video)
        else:
            total_items = 0
            non_video_count = 0
            gifs_ok = False

        # Require query parts to match our intended [title, artist]
        qp = active_deck_data.get('giphy_query_parts')
        qp_ok = (isinstance(qp, list) and qp[:2] == desired_parts) if desired_parts else True

        needs_enrichment = (not has_keywords) or (not gifs_ok) or (not qp_ok)
        # #region agent log
        _debug_log(
            "djcap_processor.py:process_metadata_update",
            "needs_enrichment_eval",
            {
                "active_deck": current_active_deck,
                "has_keywords": has_keywords,
                "gifs_ok": gifs_ok,
                "qp_ok": qp_ok,
                "total_items": total_items,
                "non_video_count": non_video_count,
                "needs_enrichment": needs_enrichment,
            },
            "GIF-H5",
        )
        # #endregion
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
            # Inactive deck (paused / not playing):
            # Keep basic metadata, but ALSO preserve the last known enriched visuals
            # for the same track so the frontend doesn't "glitch" into empty-state.
            base = {
                'deck': deck_data.get('deck'),
                'title': deck_data.get('title'),
                'artist': deck_data.get('artist'),
                'bpm': deck_data.get('bpm'),
                'key': deck_data.get('key'),
                'active': False
            }
            current_enriched = deck_data.get('current_enriched') or {}
            track_id = f"{deck_data.get('title')}|{deck_data.get('artist')}"
            last_track_id = None
            if current_enriched:
                last_track_id = f"{current_enriched.get('title')}|{current_enriched.get('artist')}"
            
            same_track = track_id == last_track_id and bool(deck_data.get('title')) and bool(deck_data.get('artist'))
            
            # #region agent log
            _debug_log(
                f"djcap_processor.py:process_deck_transition:{deck_name}",
                "inactive_deck_check",
                {
                    "deck_name": deck_name,
                    "is_active": is_active,
                    "title": deck_data.get('title'),
                    "artist": deck_data.get('artist'),
                    "bpm": deck_data.get('bpm'),
                    "track_id": track_id,
                    "last_track_id": last_track_id,
                    "same_track": same_track,
                    "has_current_enriched": bool(current_enriched),
                    "has_title": bool(deck_data.get('title')),
                    "has_artist": bool(deck_data.get('artist')),
                    "has_bpm": bool(deck_data.get('bpm')),
                },
                "MV-DEBUG-1",
            )
            # #endregion
            
            # PROACTIVE: If this is a new track in the inactive deck, start downloading its music video
            if not same_track and deck_data.get('title') and deck_data.get('artist') and deck_data.get('bpm'):
                title = deck_data.get('title')
                artist = deck_data.get('artist')
                bpm = deck_data.get('bpm')
                logger.info(f"Proactive: Detected new track in inactive {deck_name}: {title} by {artist} - starting music video download")
                # #region agent log
                _debug_log(
                    f"djcap_processor.py:process_deck_transition:{deck_name}",
                    "proactive_mv_download_inactive",
                    {
                        "track_id": track_id,
                        "last_track_id": last_track_id,
                        "title": title,
                        "artist": artist,
                        "bpm": bpm,
                        "deck_name": deck_name
                    },
                    "MV-PROACTIVE",
                )
                # #endregion
                # #region agent log
                _debug_log(
                    f"djcap_processor.py:process_deck_transition:{deck_name}",
                    "calling_maybe_start_mv_download",
                    {
                        "track_id": track_id,
                        "title": title,
                        "artist": artist,
                        "bpm": bpm,
                    },
                    "MV-DEBUG-2",
                )
                # #endregion
                _maybe_start_music_video_download(track_id, title, artist, bpm)

            preserved = {}
            if same_track:
                preserved = {
                    'lastfm_tags': current_enriched.get('lastfm_tags', []),
                    'refined_keywords': current_enriched.get('refined_keywords', []),
                    'keyword_scores': current_enriched.get('keyword_scores', {}),
                    'key_characteristics': current_enriched.get('key_characteristics', []),
                    'gifs': current_enriched.get('gifs', []),
                    'gif_pool': current_enriched.get('gif_pool', []),
                    'giphy_query': current_enriched.get('giphy_query'),
                    'giphy_query_parts': current_enriched.get('giphy_query_parts', []),
                    'google_query_parts': current_enriched.get('google_query_parts', []),
                    'track_started_at': current_enriched.get('track_started_at'),
                    'music_video_status': current_enriched.get('music_video_status'),
                    'music_video_downloaded_at': current_enriched.get('music_video_downloaded_at', 0),
                    'music_video_clips': current_enriched.get('music_video_clips', []),
                    'music_video': current_enriched.get('music_video'),
                }

            # Apply cached MV result even when paused, if available
            mv = _music_video_cache.get(track_id)
            if mv and same_track:
                preserved['music_video_status'] = mv.get('status')
                preserved['music_video_downloaded_at'] = mv.get('downloaded_at')
                preserved['music_video_clips'] = mv.get('clips') or []
                preserved['music_video'] = mv.get('video')
            elif mv and not same_track:
                # New track but MV already downloaded (from proactive download)
                preserved['music_video_status'] = mv.get('status')
                preserved['music_video_downloaded_at'] = mv.get('downloaded_at')
                preserved['music_video_clips'] = mv.get('clips') or []
                preserved['music_video'] = mv.get('video')
                logger.info(f"Proactive: Music video for {deck_name} track {track_id} is {'ready' if mv.get('status') == 'ready' else 'downloading'}")

            # #region agent log
            _debug_log(
                f"djcap_processor.py:process_deck_transition:{deck_name}",
                "inactive_deck_preserve_enriched",
                {
                    "same_track": same_track,
                    "has_current_enriched": bool(current_enriched),
                    "preserved_gifs_count": len(preserved.get("gifs") or []),
                    "preserved_has_mv": bool(preserved.get("music_video")),
                },
                "SLOT-H2",
            )
            # #endregion

            merged = {**base, **preserved}
            return merged
        
        # Active deck - handle transition
        current_enriched = deck_data.get('current_enriched')
        next_enriched = deck_data.get('next_enriched')
        
        # Check if this is a new track (title/artist changed)
        track_id = f"{deck_data.get('title')}|{deck_data.get('artist')}"
        last_track_id = None
        if current_enriched:
            last_track_id = f"{current_enriched.get('title')}|{current_enriched.get('artist')}"
        
        # #region agent log
        _debug_log(f"djcap_processor.py:process_deck_transition:{deck_name}", "Track change detection", {
            "track_id": track_id,
            "last_track_id": last_track_id,
            "has_current_enriched": bool(current_enriched),
            "deck_title": deck_data.get('title'),
            "deck_artist": deck_data.get('artist'),
            "current_enriched_title": current_enriched.get('title') if current_enriched else None,
            "current_enriched_artist": current_enriched.get('artist') if current_enriched else None
        }, "K")
        # #endregion
        
        is_new_track = track_id != last_track_id
        
        if is_new_track:
            # New track detected - move current to next, create new current
            logger.info(f"New track detected for {deck_name}: {deck_data.get('title')}")
            # #region agent log
            _debug_log(f"djcap_processor.py:process_deck_transition:{deck_name}", "New track detected", {
                "track_id": track_id,
                "last_track_id": last_track_id,
                "deck_name": deck_name
            }, "K")
            # #endregion
            
            # Move current to next (for transition)
            if current_enriched:
                deck_data['next_enriched'] = current_enriched.copy()
            
            # Start music-video download for this track (non-blocking, cached)
            title = deck_data.get('title')
            artist = deck_data.get('artist')
            bpm = deck_data.get('bpm')
            _maybe_start_music_video_download(track_id, title, artist, bpm)
            
            # Create new enriched data
            new_enriched = enrich_deck_data(deck_data)
            # Track start time for syncing (best-effort)
            new_enriched['track_started_at'] = time.time()
            deck_data['current_enriched'] = new_enriched
            
            # Copy dance_videos_overlay to top level for frontend access
            if 'dance_videos_overlay' in new_enriched:
                deck_data['dance_videos_overlay'] = new_enriched['dance_videos_overlay']
            
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
            
            # Copy dance_videos_overlay to top level for frontend access
            if current_enriched and 'dance_videos_overlay' in current_enriched:
                deck_data['dance_videos_overlay'] = current_enriched['dance_videos_overlay']

            # Ensure track_started_at exists for sync (e.g., after restart)
            if deck_data.get('current_enriched') and not deck_data['current_enriched'].get('track_started_at'):
                deck_data['current_enriched']['track_started_at'] = time.time()

            # Even if it's the same track (e.g., after restart), kick off music-video download
            # when we don't have clips yet.
            title = deck_data.get('title')
            artist = deck_data.get('artist')
            bpm = deck_data.get('bpm')
            _maybe_start_music_video_download(track_id, title, artist, bpm)
            
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
            deck_data['google_query_parts'] = current.get('google_query_parts', [])
            deck_data['dance_videos_overlay'] = current.get('dance_videos_overlay', [])
            # Apply cached music-video result into current_enriched (so djcap preserves it)
            # and also expose it directly on the deck object for the frontend.
            mv = _music_video_cache.get(track_id)
            if mv:
                current['music_video_status'] = mv.get('status')
                current['music_video_downloaded_at'] = mv.get('downloaded_at')
                current['music_video_clips'] = mv.get('clips') or []
                current['music_video'] = mv.get('video')
                deck_data['music_video_status'] = current.get('music_video_status')
                deck_data['music_video_downloaded_at'] = current.get('music_video_downloaded_at')
                deck_data['music_video_clips'] = current.get('music_video_clips')
                deck_data['music_video'] = current.get('music_video')
                # #region agent log
                _debug_log(
                    f"djcap_processor.py:process_deck_transition:{deck_name}",
                    "music_video_cache_applied",
                    {
                        "track_id": track_id,
                        "status": current.get("music_video_status"),
                        "clips_count": len(current.get("music_video_clips") or []),
                        "has_video": bool(current.get("music_video")),
                    },
                    "MV-J",
                )
                # #endregion
            # Preserve music video clips if they exist (don't overwrite if already set)
            if 'music_video_clips' not in deck_data or not deck_data.get('music_video_clips'):
                # Try to get from current enriched if not in deck_data
                if current.get('music_video_clips'):
                    deck_data['music_video_clips'] = current.get('music_video_clips', [])
            if 'music_video_downloaded_at' not in deck_data:
                deck_data['music_video_downloaded_at'] = deck_data.get('music_video_downloaded_at') or current.get('music_video_downloaded_at', 0)
            logger.info(
                f"After merge for {deck_name}: gifs={len(deck_data['gifs'])}, "
                f"has_current_enriched={'current_enriched' in deck_data}, "
                f"music_video_clips={len(deck_data.get('music_video_clips', []))}"
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
        
        # Cleanup old music videos
        _cleanup_old_music_videos(data)
        
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

