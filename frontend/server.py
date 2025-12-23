#!/usr/bin/env python3
"""
Simple HTTP server for DjCap frontend.
Serves the Vue.js frontend and provides API endpoint for enriched JSON data.
"""
import http.server
import socketserver
import json
import os
import logging
import re
import time
import shutil
import hashlib
import mimetypes
from pathlib import Path
from urllib.parse import urlparse, parse_qs, quote, unquote
import urllib.request
import urllib.error
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configuration
PORT = 8080
OUTPUT_JSON_PATH = Path(__file__).parent.parent / "data" / "output" / "djcap_output.json"
FRONTEND_DIR = Path(__file__).parent
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "output"
REGION_COORDS_PATH = Path(__file__).parent.parent / "data" / "region_coordinates.json"
MEDIA_CACHE_DIR = Path(__file__).parent.parent / "data" / "cache" / "media"
MEDIA_CACHE_STATE_PATH = MEDIA_CACHE_DIR / "state.json"
MEDIA_CACHE_DELETE_AFTER_S = 60


def _sanitize_cache_key(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return "unknown"
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", s)
    s = s.strip("_")
    return (s[:120] if len(s) > 120 else s) or "unknown"


def _is_local_url(url: str) -> bool:
    if not url:
        return True
    if url.startswith("/"):
        return True
    if url.startswith("http://localhost") or url.startswith("http://127.0.0.1"):
        return True
    return False


def _guess_ext(url: str, content_type: str) -> str:
    try:
        p = urlparse(url)
        ext = os.path.splitext(p.path)[1].lower()
        if ext and len(ext) <= 6:
            return ext
    except Exception:
        pass
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct == "image/gif":
        return ".gif"
    if ct == "image/webp":
        return ".webp"
    if ct in {"image/jpeg", "image/jpg"}:
        return ".jpg"
    if ct == "image/png":
        return ".png"
    if ct == "video/mp4":
        return ".mp4"
    return ".bin"


def _load_media_cache_state() -> dict:
    try:
        if MEDIA_CACHE_STATE_PATH.exists():
            return json.loads(MEDIA_CACHE_STATE_PATH.read_text())
    except Exception:
        pass
    return {"tracks": {}, "updated_at": None}


def _save_media_cache_state(state: dict) -> None:
    MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MEDIA_CACHE_STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    os.replace(tmp, MEDIA_CACHE_STATE_PATH)


def _cleanup_media_cache(now_s: float) -> None:
    state = _load_media_cache_state()
    tracks = state.get("tracks") or {}

    # Delete any tracks whose delete_after has passed
    for track_key, info in list(tracks.items()):
        delete_after = info.get("delete_after")
        if delete_after is not None and float(delete_after) <= now_s:
            folder = MEDIA_CACHE_DIR / track_key
            try:
                if folder.exists():
                    shutil.rmtree(folder, ignore_errors=True)
            except Exception:
                pass
            try:
                tracks.pop(track_key, None)
            except Exception:
                pass

    state["tracks"] = tracks
    state["updated_at"] = now_s
    try:
        _save_media_cache_state(state)
    except Exception:
        pass


class ReusableTCPServer(socketserver.TCPServer):
    # Avoid "Address already in use" on quick restarts (TIME_WAIT)
    allow_reuse_address = True


class DjcapHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def end_headers(self):
        # Disable caching so UI changes in index.html/viewer.html show up immediately.
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_GET(self):
        parsed_path = urlparse(self.path)
        
        # API endpoint for output JSON (now contains all enriched data)
        if parsed_path.path == '/api/enriched':
            self.serve_output_json()
        # API endpoint for dance videos
        elif parsed_path.path.startswith('/api/dance_video/'):
            self.serve_dance_video(parsed_path.path.replace('/api/dance_video/', ''))
        # API endpoint for proxying external GIFs (to avoid CORS issues)
        elif parsed_path.path.startswith('/api/proxy_gif/'):
            self.serve_proxied_gif(parsed_path.path.replace('/api/proxy_gif/', ''))
        # API endpoint for cached media (prefetched GIFs/videos)
        elif parsed_path.path.startswith('/api/cache_media/'):
            self.serve_cached_media(parsed_path.path.replace('/api/cache_media/', ''))
        # API endpoint for music video clips
        elif parsed_path.path.startswith('/api/music_video_clip/'):
            self.serve_music_video_clip(parsed_path.path.replace('/api/music_video_clip/', ''))
        # API endpoint for full downloaded music videos
        elif parsed_path.path.startswith('/api/music_video/'):
            self.serve_music_video(parsed_path.path.replace('/api/music_video/', ''))
        # Debug: serve a single overlay PNG showing time OCR ROIs
        elif parsed_path.path == "/api/debug/time_rois.png":
            self.serve_debug_image("time_rois_debug.png")
        elif parsed_path.path == "/api/debug/last_capture.png":
            self.serve_debug_image("last_capture.png")
        elif parsed_path.path == "/api/debug/time_rois_saved.png":
            self.serve_saved_time_rois_overlay()
        # Calibration: read current region coordinates
        elif parsed_path.path == "/api/calibrate/region_coordinates":
            self.serve_region_coordinates()
        else:
            # Serve static files
            super().do_GET()

    def do_POST(self):
        parsed_path = urlparse(self.path)

        if parsed_path.path == "/api/calibrate/time_roi":
            self.save_time_roi()
        elif parsed_path.path == "/api/prefetch_media":
            self.prefetch_media()
        else:
            self.send_response(404)
            self.end_headers()

    def _read_json_body(self, max_bytes: int = 64_000) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0 or length > max_bytes:
            raise ValueError("invalid_content_length")
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def serve_cached_media(self, rest: str):
        """
        Serve a cached file: /api/cache_media/<track_key>/<filename>
        Supports Range for mp4.
        """
        try:
            rest = rest.lstrip("/")
            parts = rest.split("/", 1)
            if len(parts) != 2:
                self.send_response(400)
                self.end_headers()
                return
            track_key = _sanitize_cache_key(unquote(parts[0]))
            filename = unquote(parts[1])
            if ".." in filename or "/" in filename or "\\" in filename:
                self.send_response(400)
                self.end_headers()
                return

            path = MEDIA_CACHE_DIR / track_key / filename
            if not path.exists() or not path.is_file():
                try:
                    logging.getLogger(__name__).warning(
                        f"cache_media 404 track_key={track_key} filename={filename}"
                    )
                except Exception:
                    pass
                self.send_response(404)
                self.end_headers()
                return

            content_type, _ = mimetypes.guess_type(str(path))
            content_type = content_type or "application/octet-stream"
            file_size = path.stat().st_size
            range_header = self.headers.get("Range")

            start = 0
            end = file_size - 1
            status_code = 200

            if range_header and content_type == "video/mp4":
                m = re.match(r"bytes=(\d*)-(\d*)", range_header)
                if m:
                    start_s, end_s = m.groups()
                    if start_s:
                        start = int(start_s)
                    if end_s:
                        end = int(end_s)
                if start >= file_size or start < 0 or end < start:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{file_size}")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    return
                if end >= file_size:
                    end = file_size - 1
                status_code = 206

            # Generate ETag from file hash for better caching
            try:
                # Use file mtime + size for ETag (faster than full hash)
                stat = path.stat()
                file_hash = hashlib.md5(f"{stat.st_mtime}_{stat.st_size}".encode()).hexdigest()
                etag = f'"{file_hash}"'
            except Exception:
                etag = None

            # Check If-None-Match for conditional requests
            if_none_match = self.headers.get("If-None-Match")
            if if_none_match and etag and if_none_match.strip() == etag:
                self.send_response(304)  # Not Modified
                self.send_header("Content-Type", content_type)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                return

            self.send_response(status_code)
            self.send_header("Content-Type", content_type)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "public, max-age=86400")  # 24 hours instead of 1 hour
            if etag:
                self.send_header("ETag", etag)
            if status_code == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.send_header("Content-Length", str(end - start + 1))
            else:
                self.send_header("Content-Length", str(file_size))
            self.end_headers()

            with open(path, "rb") as f:
                if start:
                    f.seek(start)
                to_send = end - start + 1
                while to_send > 0:
                    chunk = f.read(min(1024 * 256, to_send))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    to_send -= len(chunk)

        except Exception as e:
            logging.getLogger(__name__).error(f"Error serving cached media: {e}", exc_info=True)
            self.send_response(500)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

    def prefetch_media(self):
        """
        Download all external media for a track into data/cache/media/<track_key>/ and return a mapping.
        Body:
          {
            "track_id": "Title|Artist" (or any string),
            "items": [{"url": "...", "mime": "image/gif"|"video/mp4"|..., "id": "..."}]
          }
        """
        try:
            body = self._read_json_body(max_bytes=2_000_000)
            track_id = str(body.get("track_id") or "").strip()
            items = body.get("items") or []
            if not track_id:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "track_id required"}).encode("utf-8"))
                return

            track_key = _sanitize_cache_key(track_id)
            track_dir = MEDIA_CACHE_DIR / track_key
            track_dir.mkdir(parents=True, exist_ok=True)

            # Update deletion schedule: keep current track; schedule others for deletion soon.
            now_s = time.time()
            state = _load_media_cache_state()
            tracks = state.get("tracks") or {}
            for k, info in list(tracks.items()):
                if k != track_key:
                    if info.get("delete_after") is None:
                        info["delete_after"] = now_s + MEDIA_CACHE_DELETE_AFTER_S
                        tracks[k] = info
            tracks.setdefault(track_key, {})["delete_after"] = None
            state["tracks"] = tracks
            state["updated_at"] = now_s
            _save_media_cache_state(state)
            _cleanup_media_cache(now_s)

            cached = {}
            skipped = []
            failed = []

            # Deduplicate by URL
            seen = set()
            download_tasks = []
            
            for it in items:
                url = (it or {}).get("url") if isinstance(it, dict) else None
                url = str(url or "").strip()
                if not url:
                    continue
                original_url = url
                if original_url in seen:
                    continue
                seen.add(original_url)

                if _is_local_url(original_url):
                    skipped.append(original_url)
                    continue

                download_tasks.append(original_url)

            # Download in parallel with concurrency limit (4 workers)
            def download_media_item(original_url):
                try:
                    # Check if already cached
                    ext_guess = _guess_ext(original_url, "")
                    name_guess = hashlib.sha1(original_url.encode("utf-8")).hexdigest() + ext_guess
                    out_path = track_dir / name_guess
                    
                    # If file exists, return cached URL
                    if out_path.exists():
                        return (original_url, f"/api/cache_media/{quote(track_key)}/{quote(name_guess)}", None)
                    
                    # Download
                    req = urllib.request.Request(original_url)
                    req.add_header("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
                    req.add_header("Accept", "*/*")
                    req.add_header("Accept-Language", "en-US,en;q=0.9")
                    req.add_header("Referer", "https://www.google.com/")

                    with urllib.request.urlopen(req, timeout=20) as resp:
                        content_type = resp.headers.get("Content-Type", "")
                        data = resp.read()

                    ext = _guess_ext(original_url, content_type)
                    name = hashlib.sha1(original_url.encode("utf-8")).hexdigest() + ext
                    out_path = track_dir / name

                    # Double-check existence (race condition protection)
                    if not out_path.exists():
                        out_path.write_bytes(data)

                    return (original_url, f"/api/cache_media/{quote(track_key)}/{quote(name)}", None)
                except Exception as e:
                    return (original_url, None, str(e)[:200])

            # Execute downloads in parallel with max 4 workers
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_url = {executor.submit(download_media_item, url): url for url in download_tasks}
                
                for future in as_completed(future_to_url):
                    original_url, cached_url, error = future.result()
                    if cached_url:
                        cached[original_url] = cached_url
                    elif error:
                        failed.append({"url": original_url, "error": error})

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({
                "ok": True,
                "track_id": track_id,
                "track_key": track_key,
                "counts": {
                    "total_items": len(items),
                    "cached": len(cached),
                    "skipped": len(skipped),
                    "failed": len(failed),
                },
                "cached": cached,
                "skipped": skipped,
                "failed": failed,
            }).encode("utf-8"))
        except Exception as e:
            logging.getLogger(__name__).error(f"Error in prefetch_media: {e}", exc_info=True)
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

    def serve_region_coordinates(self):
        try:
            if REGION_COORDS_PATH.exists():
                data = json.loads(REGION_COORDS_PATH.read_text())
            else:
                data = {}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

    def save_time_roi(self):
        """
        Save a calibrated time ROI into data/region_coordinates.json.
        Body: {"deck":"deck1"|"deck2", "roi":[x1,y1,x2,y2]}
        Coordinates are in full-screenshot pixels.
        """
        try:
            body = self._read_json_body()
            deck = body.get("deck")
            roi = body.get("roi")

            if deck not in {"deck1", "deck2"}:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "deck must be deck1 or deck2"}).encode("utf-8"))
                return

            if not isinstance(roi, list) or len(roi) != 4:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "roi must be [x1,y1,x2,y2]"}).encode("utf-8"))
                return

            try:
                x1, y1, x2, y2 = [int(v) for v in roi]
            except Exception:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "roi values must be ints"}).encode("utf-8"))
                return

            # Normalize so x1<x2, y1<y2
            if x2 < x1:
                x1, x2 = x2, x1
            if y2 < y1:
                y1, y2 = y2, y1
            if x2 == x1 or y2 == y1:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "roi has zero area"}).encode("utf-8"))
                return

            # Load existing coords (if any)
            if REGION_COORDS_PATH.exists():
                coords = json.loads(REGION_COORDS_PATH.read_text())
            else:
                coords = {}

            coords[f"{deck}_time_roi"] = [x1, y1, x2, y2]

            # Atomic write
            REGION_COORDS_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = REGION_COORDS_PATH.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(coords, indent=2, ensure_ascii=False))
            os.replace(tmp, REGION_COORDS_PATH)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "saved": f"{deck}_time_roi", "roi": [x1, y1, x2, y2]}).encode("utf-8"))
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

    def serve_saved_time_rois_overlay(self):
        """Render an overlay PNG showing the SAVED deck1_time_roi/deck2_time_roi boxes on last_capture.png."""
        try:
            capture_path = OUTPUT_DIR / "last_capture.png"
            if not capture_path.exists() or not capture_path.is_file():
                self.send_response(404)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(b"last_capture.png not found. Start/restart djcap.py first.")
                return

            if REGION_COORDS_PATH.exists():
                coords = json.loads(REGION_COORDS_PATH.read_text())
            else:
                coords = {}

            deck1_roi = coords.get("deck1_time_roi")
            deck2_roi = coords.get("deck2_time_roi")

            from PIL import Image, ImageDraw

            img = Image.open(capture_path).convert("RGB")
            draw = ImageDraw.Draw(img)

            def _draw_roi(roi, color, label):
                if not isinstance(roi, list) or len(roi) != 4:
                    return False
                try:
                    x1, y1, x2, y2 = [int(v) for v in roi]
                except Exception:
                    return False
                # normalize
                if x2 < x1:
                    x1, x2 = x2, x1
                if y2 < y1:
                    y1, y2 = y2, y1
                if x2 <= x1 or y2 <= y1:
                    return False
                draw.rectangle((x1, y1, x2, y2), outline=color, width=6)
                try:
                    draw.rectangle((x1, max(0, y1 - 24), x1 + 220, y1), fill=(0, 0, 0))
                    draw.text((x1 + 8, max(0, y1 - 22)), label, fill=color)
                except Exception:
                    pass
                return True

            ok1 = _draw_roi(deck1_roi, (255, 0, 0), "Deck1 SAVED time ROI")
            ok2 = _draw_roi(deck2_roi, (0, 255, 0), "Deck2 SAVED time ROI")

            if not ok1 and not ok2:
                self.send_response(404)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(b"No saved time ROIs found. Calibrate Deck1/Deck2 first.")
                return

            buf = BytesIO()
            img.save(buf, format="PNG")
            payload = buf.getvalue()

            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except Exception as e:
            logging.getLogger(__name__).error(f"Error serving saved time ROI overlay: {e}", exc_info=True)
            self.send_response(500)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

    def serve_debug_image(self, filename: str):
        """Serve a debug image from data/output (no-cache)."""
        try:
            # Only allow known files
            if filename not in {"time_rois_debug.png", "last_capture.png"}:
                self.send_response(400)
                self.end_headers()
                return

            p = OUTPUT_DIR / filename
            if not p.exists() or not p.is_file():
                self.send_response(404)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(b"Debug image not found yet. Restart djcap.py to generate it once.")
                return

            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with open(p, "rb") as f:
                self.wfile.write(f.read())
        except Exception as e:
            logging.getLogger(__name__).error(f"Error serving debug image {filename}: {e}", exc_info=True)
            self.send_response(500)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

    def serve_output_json(self):
        """Serve the output JSON file (for activity checks) with CORS headers."""
        try:
            if OUTPUT_JSON_PATH.exists():
                # Generate ETag from file mtime + size for conditional requests
                try:
                    stat = OUTPUT_JSON_PATH.stat()
                    file_hash = hashlib.md5(f"{stat.st_mtime}_{stat.st_size}".encode()).hexdigest()
                    etag = f'"{file_hash}"'
                except Exception:
                    etag = None
                
                # Check If-None-Match for conditional requests
                if_none_match = self.headers.get("If-None-Match")
                if if_none_match and etag and if_none_match.strip() == etag:
                    self.send_response(304)  # Not Modified
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.send_header('Access-Control-Allow-Methods', 'GET')
                    self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                    if etag:
                        self.send_header('ETag', etag)
                    self.end_headers()
                    return
                
                with open(OUTPUT_JSON_PATH, 'r') as f:
                    data = json.load(f)
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                if etag:
                    self.send_header('ETag', etag)
                self.end_headers()
                self.wfile.write(json.dumps(data).encode('utf-8'))
            else:
                self.send_response(404)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Output JSON not found'}).encode('utf-8'))
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))

    def serve_dance_video(self, filename: str):
        """Serve dance video files from the dance_mp4_bank folder as 1-second clips with fade in/out."""
        try:
            # Security: only allow .mp4 files and prevent directory traversal
            if not filename.endswith('.mp4') or '..' in filename or '/' in filename:
                self.send_response(400)
                self.end_headers()
                return
            
            video_path = Path(__file__).parent.parent / "data" / "dance_mp4_bank" / filename
            
            if not video_path.exists() or not video_path.is_file():
                self.send_response(404)
                self.end_headers()
                return
            
            # Check if we should serve as 1-second clip with fade
            # Parse start time from query string if provided, otherwise use 0
            import time
            serve_start_time = time.time()
            parsed_path = urlparse(self.path)
            query_params = parse_qs(parsed_path.query)
            start_time = float(query_params.get('start', ['0'])[0])
            clip_duration = 1.0  # 1 second
            fade_duration = 0.1  # 100ms fade in/out
            
            # #region agent log
            try:
                import json
                log_entry = {
                    "location": "server.py:serve_dance_video",
                    "message": "serve_start",
                    "data": {
                        "filename": filename,
                        "start_time": start_time,
                        "clip_duration": clip_duration
                    },
                    "timestamp": int(time.time() * 1000),
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "H2"
                }
                with open(Path(__file__).parent.parent / ".cursor" / "debug.log", "a") as f:
                    f.write(json.dumps(log_entry) + "\n")
            except:
                pass
            # #endregion
            
            # Serve 1-second clip with fade in/out on-the-fly
            import subprocess
            ffmpeg_start_time = time.time()
            # Ensure minimum bitrate and keyframe interval for valid MP4 files
            cmd = [
                'ffmpeg', '-i', str(video_path),
                '-ss', str(start_time),
                '-t', str(clip_duration),
                '-vf', f'fade=t=in:st=0:d={fade_duration},fade=t=out:st={clip_duration - fade_duration}:d={fade_duration}',
                '-c:v', 'libx264', '-preset', 'ultrafast',
                '-b:v', '500k',  # Minimum bitrate to ensure valid file
                '-g', '30',  # Keyframe interval
                '-c:a', 'aac', '-b:a', '64k',
                '-f', 'mp4',
                '-movflags', 'frag_keyframe+empty_moov+faststart',
                '-'  # Output to stdout
            ]
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            self.send_response(200)
            self.send_header('Content-Type', 'video/mp4')
            self.send_header('Cache-Control', 'public, max-age=3600')
            self.end_headers()
            
            try:
                bytes_sent = 0
                while True:
                    chunk = process.stdout.read(8192)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    bytes_sent += len(chunk)
                process.wait()
                serve_end_time = time.time()
                # #region agent log
                try:
                    log_entry = {
                        "location": "server.py:serve_dance_video",
                        "message": "serve_complete",
                        "data": {
                            "filename": filename,
                            "start_time": start_time,
                            "ffmpeg_duration_ms": (serve_end_time - ffmpeg_start_time) * 1000,
                            "total_duration_ms": (serve_end_time - serve_start_time) * 1000,
                            "bytes_sent": bytes_sent,
                            "returncode": process.returncode
                        },
                        "timestamp": int(time.time() * 1000),
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "H2"
                    }
                    with open(Path(__file__).parent.parent / ".cursor" / "debug.log", "a") as f:
                        f.write(json.dumps(log_entry) + "\n")
                except:
                    pass
                # #endregion
            except Exception as e:
                logging.error(f"Error streaming dance video clip: {e}")
                try:
                    process.terminate()
                except:
                    pass
            return
        except Exception as e:
            logging.error(f"Error serving dance video {filename}: {e}")
            self.send_response(500)
            self.end_headers()
            trim_duration = None
            try:
                from src.video_trimming import get_video_trim_info
                trim_duration = get_video_trim_info(video_path)
            except Exception as e:
                # If trimming module fails, just serve full file
                pass
            
            # If trimming is needed, use ffmpeg to serve only the trimmed portion
            if trim_duration is not None and trim_duration > 0:
                import subprocess
                
                try:
                    # Use ffmpeg to extract and serve only the trimmed portion
                    # Using re-encoding for better compatibility (fragmented MP4)
                    cmd = [
                        'ffmpeg',
                        '-i', str(video_path),
                        '-t', str(trim_duration),
                        '-c:v', 'libx264',  # Re-encode for compatibility
                        '-preset', 'ultrafast',  # Fast encoding
                        '-crf', '28',  # Lower quality for speed
                        '-c:a', 'aac',  # Audio codec
                        '-f', 'mp4',
                        '-movflags', 'frag_keyframe+empty_moov',  # Streaming-friendly format
                        '-'  # Output to stdout
                    ]
                    
                    process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,  # Suppress ffmpeg logs
                        bufsize=8192
                    )
                    
                    self.send_response(200)
                    self.send_header('Content-Type', 'video/mp4')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.send_header('Cache-Control', 'public, max-age=3600')
                    self.end_headers()
                    
                    # Stream the trimmed video
                    try:
                        while True:
                            chunk = process.stdout.read(8192)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                        process.wait()
                    except (BrokenPipeError, ConnectionResetError):
                        # Client disconnected, kill process
                        process.kill()
                        process.wait()
                        return
                    except Exception:
                        process.kill()
                        process.wait()
                        raise
                    
                    if process.returncode != 0:
                        raise Exception("ffmpeg failed")
                    
                    return  # Successfully served trimmed video
                    
                except Exception as e:
                    # Fallback: serve full file if trimming fails
                    logger = logging.getLogger(__name__)
                    logger.warning(f"Failed to trim video {filename}, serving full file: {e}")
                    # Continue to serve full file below
            
            # No trimming needed or trimming failed, serve full file
            self.send_response(200)
            self.send_header('Content-Type', 'video/mp4')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'public, max-age=3600')
            self.end_headers()
            
            with open(video_path, 'rb') as f:
                self.wfile.write(f.read())
                    
        except Exception as e:
            self.send_response(500)
            self.end_headers()

    def serve_proxied_gif(self, encoded_url: str):
        """Proxy external GIFs to avoid CORS issues."""
        try:
            # First, URL-decode the path parameter (browser may have encoded + and /)
            from urllib.parse import unquote
            import base64
            
            # URL-decode first (handles %2B -> +, %2F -> /, etc.)
            url_decoded = unquote(encoded_url)
            
            decoded_url = None
            try:
                # Try base64 decoding (standard base64 from btoa())
                # Add padding if needed
                padding = 4 - len(url_decoded) % 4
                if padding != 4:
                    url_decoded += '=' * padding
                decoded_url = base64.b64decode(url_decoded).decode('utf-8')
                logging.getLogger(__name__).debug(f"Decoded URL (base64): {decoded_url[:100]}...")
            except Exception as e1:
                # If base64 fails, try using the URL-decoded string as-is
                # (might be URL-encoded but not base64)
                try:
                    decoded_url = unquote(url_decoded)  # Double decode in case
                    logging.getLogger(__name__).debug(f"Decoded URL (double URL decode): {decoded_url[:100]}...")
                except Exception as e2:
                    # If both fail, use the URL-decoded string as-is
                    decoded_url = url_decoded
                    logging.getLogger(__name__).debug(f"Using URL-decoded string as-is: {decoded_url[:100]}...")
            
            # Validate URL
            parsed = urlparse(decoded_url)
            if not parsed.scheme or not parsed.netloc:
                self.send_response(400)
                self.end_headers()
                return
            
            # Only allow http/https URLs for security
            if parsed.scheme not in ['http', 'https']:
                self.send_response(400)
                self.end_headers()
                return
            
            # Fetch the image with better headers to avoid blocking
            try:
                req = urllib.request.Request(decoded_url)
                # Use a more realistic browser user agent
                req.add_header('User-Agent', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
                req.add_header('Accept', 'image/webp,image/apng,image/*,*/*;q=0.8')
                req.add_header('Accept-Language', 'en-US,en;q=0.9')
                req.add_header('Referer', 'https://www.google.com/')
                req.add_header('Sec-Fetch-Dest', 'image')
                req.add_header('Sec-Fetch-Mode', 'no-cors')
                req.add_header('Sec-Fetch-Site', 'cross-site')
                
                with urllib.request.urlopen(req, timeout=10) as response:
                    content_type = response.headers.get('Content-Type', 'image/gif')
                    content = response.read()
                    
                    self.send_response(200)
                    self.send_header('Content-Type', content_type)
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.send_header('Cache-Control', 'public, max-age=3600')
                    self.end_headers()
                    self.wfile.write(content)
            except urllib.error.HTTPError as e:
                # Log the error for debugging
                logging.getLogger(__name__).warning(f"HTTP error {e.code} when fetching {decoded_url}: {e.reason}")
                # Try to read error response for debugging
                try:
                    error_body = e.read().decode('utf-8')
                    logging.getLogger(__name__).debug(f"Error response body: {error_body[:200]}")
                except:
                    pass
                # Return 502 (Bad Gateway) instead of passing through 403 to avoid CORS issues
                self.send_response(502)
                self.send_header('Content-Type', 'text/plain')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(f"Failed to fetch image: {e.code} {e.reason}".encode('utf-8'))
            except urllib.error.URLError as e:
                logging.getLogger(__name__).warning(f"URL error when fetching {decoded_url}: {e}")
                self.send_response(502)
                self.send_header('Content-Type', 'text/plain')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(f"Failed to fetch image: {str(e)}".encode('utf-8'))
            except Exception as e:
                logging.getLogger(__name__).error(f"Error proxying GIF {decoded_url}: {e}", exc_info=True)
                self.send_response(500)
                self.send_header('Content-Type', 'text/plain')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(f"Internal server error: {str(e)}".encode('utf-8'))
                
        except Exception as e:
            logging.getLogger(__name__).error(f"Error in serve_proxied_gif: {e}")
            self.send_response(500)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

    def serve_music_video_clip(self, relative_path: str):
        """Serve precut music video clips."""
        try:
            # Security: prevent directory traversal
            if '..' in relative_path:
                self.send_response(400)
                self.end_headers()
                return
            
            video_path = Path(__file__).parent.parent / "data" / relative_path
            
            if not video_path.exists() or not video_path.is_file() or not video_path.suffix == '.mp4':
                self.send_response(404)
                self.end_headers()
                return
            
            # Serve the clip
            self.send_response(200)
            self.send_header('Content-Type', 'video/mp4')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'public, max-age=3600')
            self.end_headers()
            
            with open(video_path, 'rb') as f:
                self.wfile.write(f.read())
                    
        except Exception as e:
            self.send_response(500)
            self.end_headers()

    def serve_music_video(self, filename: str):
        """Serve a full downloaded music video file from data/music_videos, with HTTP Range support."""
        try:
            # URL-decode (%20 etc.) so we can locate the real file on disk.
            # Note: do this before traversal checks because decoded form is what hits the filesystem.
            filename = unquote(filename)

            # Security: prevent directory traversal
            if '..' in filename or '/' in filename or '\\' in filename:
                self.send_response(400)
                self.end_headers()
                return

            # Primary location: inside project data/music_videos
            video_path = Path(__file__).parent.parent / "data" / "music_videos" / filename
            # Backward-compatible fallback: older runs stored in ~/data/music_videos
            if not video_path.exists():
                alt_path = Path.home() / "data" / "music_videos" / filename
                if alt_path.exists():
                    video_path = alt_path

            if not video_path.exists() or not video_path.is_file():
                self.send_response(404)
                self.end_headers()
                return

            # Only allow mp4 for now
            if video_path.suffix.lower() != ".mp4":
                self.send_response(400)
                self.end_headers()
                return

            logger = logging.getLogger(__name__)
            file_size = video_path.stat().st_size
            range_header = self.headers.get("Range")

            # Default full range
            start = 0
            end = file_size - 1
            status_code = 200

            if range_header:
                # Example: "bytes=0-1023"
                m = re.match(r"bytes=(\d*)-(\d*)", range_header)
                if m:
                    start_s, end_s = m.groups()
                    if start_s:
                        start = int(start_s)
                    if end_s:
                        end = int(end_s)

                # Validate
                if start >= file_size or start < 0 or end < start:
                    self.send_response(416)  # Range Not Satisfiable
                    self.send_header("Content-Range", f"bytes */{file_size}")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    return

                if end >= file_size:
                    end = file_size - 1

                status_code = 206

            # Minimal instrumentation (helps debug black box / buffering)
            try:
                logger.info(
                    f"music_video serve filename={filename!r} size={file_size} "
                    f"range={range_header!r} status={status_code} start={start} end={end}"
                )
            except Exception:
                pass

            self.send_response(status_code)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Accept-Ranges", "bytes")

            if status_code == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.send_header("Content-Length", str(end - start + 1))
            else:
                self.send_header("Content-Length", str(file_size))

            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()

            with open(video_path, "rb") as f:
                if start:
                    f.seek(start)
                to_send = end - start + 1
                while to_send > 0:
                    chunk = f.read(min(1024 * 256, to_send))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    to_send -= len(chunk)

        except Exception as e:
            logging.getLogger(__name__).error(f"Error serving music video {filename}: {e}", exc_info=True)
            self.send_response(500)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

    def log_message(self, format, *args):
        """Override to reduce log noise."""
        pass


def main():
    """Start the HTTP server."""
    with ReusableTCPServer(("", PORT), DjcapHandler) as httpd:
        print(f"🎧 DjCap Frontend Server")
        print(f"=" * 50)
        print(f"Server running at http://localhost:{PORT}")
        print(f"Serving frontend from: {FRONTEND_DIR}")
        print(f"Reading JSON from: {OUTPUT_JSON_PATH}")
        print(f"=" * 50)
        print(f"Press Ctrl+C to stop")
        print()
        
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n\nServer stopped.")


if __name__ == "__main__":
    main()

