#!/usr/bin/env python3
"""
Simple HTTP server for DjCap frontend.
Serves the Vue.js frontend and provides API endpoint for enriched JSON data.
"""
import http.server
import socketserver
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from datetime import datetime

# Load environment variables from repo-root .env if present.
# (Useful for OPENAI_API_KEY, etc.)
try:
    from dotenv import load_dotenv  # type: ignore
    repo_root_env = Path(__file__).resolve().parent.parent / ".env"
    if repo_root_env.exists():
        load_dotenv(repo_root_env)
except Exception:
    # If python-dotenv isn't installed or anything goes wrong, fall back to OS env vars.
    pass

# Make repo root importable so we can import `services/*` from this frontend script.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.mood_agent import generate_the_mood  # noqa: E402

# Configuration
PORT = 8080
OUTPUT_JSON_PATH = Path(__file__).parent.parent / "data" / "output" / "djcap_output.json"
FRONTEND_DIR = Path(__file__).parent


class DjcapHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def do_GET(self):
        parsed_path = urlparse(self.path)
        query = parse_qs(parsed_path.query or "")
        
        # API endpoint for output JSON (now contains all enriched data)
        if parsed_path.path == '/api/enriched':
            self.serve_output_json()
        elif parsed_path.path == '/api/theMood':
            # Support GET for "current mood" so clients can poll without needing OpenAI.
            # (POST /api/theMood remains available for the generation workflow.)
            include_details = query.get("includeDetails", ["0"])[0] in ("1", "true", "yes", "on")
            self.serve_the_mood(include_details=include_details)
        elif parsed_path.path == '/api/currentMood':
            include_details = query.get("includeDetails", ["0"])[0] in ("1", "true", "yes", "on")
            self.serve_the_mood(include_details=include_details)
        else:
            # Serve static files
            super().do_GET()

    def do_OPTIONS(self):
        # CORS preflight
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()

    def do_POST(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == '/api/theMood':
            self.handle_the_mood()
        else:
            self._send_json(404, {"error": "Not found"})

    def _send_json(self, status_code: int, payload: dict):
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode('utf-8'))

    def serve_output_json(self):
        """Serve the output JSON file (for activity checks) with CORS headers."""
        try:
            if OUTPUT_JSON_PATH.exists():
                with open(OUTPUT_JSON_PATH, 'r') as f:
                    data = json.load(f)
                self._send_json(200, data)
            else:
                self._send_json(404, {'error': 'Output JSON not found'})
        except Exception as e:
            self._send_json(500, {'error': str(e)})

    def _pick_active_deck(self, data: dict) -> str:
        deck1_active = bool(data.get("deck1", {}).get("active", False))
        deck2_active = bool(data.get("deck2", {}).get("active", False))
        if deck1_active and not deck2_active:
            return "deck1"
        if deck2_active and not deck1_active:
            return "deck2"
        # Fallback to explicit field (or deck1 if missing)
        return data.get("active_deck") or "deck1"

    def _compute_mood(self, deck: dict) -> tuple[str, list[str], str]:
        """
        Return (mood, mood_terms, source).
        - Prefer enriched mood-ish terms (key_characteristics / refined_keywords)
        - Fall back to key (Camelot major/minor) + BPM heuristic
        """
        # 1) Prefer key characteristics (these are explicitly mood descriptors)
        key_chars = deck.get("key_characteristics")
        if isinstance(key_chars, list) and key_chars:
            mood_terms = [str(x) for x in key_chars if x]
            return mood_terms[0], mood_terms[:5], "key_characteristics"

        # 2) Next: look for common mood adjectives in refined keywords
        refined = deck.get("refined_keywords")
        if isinstance(refined, list) and refined:
            moodish = []
            for kw in refined:
                if not kw:
                    continue
                s = str(kw).strip()
                if not s:
                    continue
                # Simple heuristic: accept single-word-ish descriptors, avoid long titles
                if len(s) <= 16 and " " not in s:
                    moodish.append(s)
            if moodish:
                return moodish[0], moodish[:5], "refined_keywords"

        # 3) Fallback heuristic: BPM energy + key mode (Camelot A=minor, B=major)
        bpm = deck.get("bpm")
        try:
            bpm_val = float(bpm) if bpm is not None else None
        except (TypeError, ValueError):
            bpm_val = None

        key = (deck.get("key") or "").strip().upper()
        is_major = key.endswith("B")
        is_minor = key.endswith("A")

        if bpm_val is None:
            energy = "steady"
        elif bpm_val >= 140:
            energy = "intense"
        elif bpm_val >= 120:
            energy = "energetic"
        elif bpm_val >= 100:
            energy = "groovy"
        elif bpm_val >= 80:
            energy = "chill"
        else:
            energy = "mellow"

        if is_major:
            vibe = "bright"
        elif is_minor:
            vibe = "moody"
        else:
            vibe = "neutral"

        mood = f"{energy}-{vibe}"
        return mood, [energy, vibe], "bpm_key"

    def serve_the_mood(self, include_details: bool = False):
        """Serve a lightweight 'current mood' derived from the active deck."""
        try:
            if not OUTPUT_JSON_PATH.exists():
                return self._send_json(404, {"error": "Output JSON not found"})

            with open(OUTPUT_JSON_PATH, "r") as f:
                data = json.load(f)

            active_deck_name = self._pick_active_deck(data)
            deck = data.get(active_deck_name, {}) if isinstance(data, dict) else {}
            mood, mood_terms, source = self._compute_mood(deck if isinstance(deck, dict) else {})

            payload = {
                "mood": mood,
                "mood_terms": mood_terms,
                "source": source,
                "active_deck": active_deck_name,
                "timestamp": datetime.now().isoformat(),
            }

            if include_details:
                payload["track"] = {
                    "title": deck.get("title"),
                    "artist": deck.get("artist"),
                    "bpm": deck.get("bpm"),
                    "key": deck.get("key"),
                    "active": deck.get("active"),
                }

            return self._send_json(200, payload)
        except Exception as e:
            return self._send_json(500, {"error": str(e)})

    def handle_the_mood(self):
        """
        POST /api/theMood

        Body JSON:
          {
            "artist": "...",
            "title": "...",
            "secondary": {"artist":"...","title":"..."} (optional),
            "max_keywords": 18 (optional),
            "max_scene_sentences": 2 (optional)
          }
        """
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length > 0 else b"{}"
            body = json.loads(raw.decode("utf-8") or "{}")

            artist = (body.get("artist") or "").strip()
            title = (body.get("title") or "").strip()
            secondary = body.get("secondary", None)
            max_keywords = int(body.get("max_keywords", 18) or 18)
            max_scene_sentences = int(body.get("max_scene_sentences", 2) or 2)

            if not artist or not title:
                return self._send_json(400, {"error": "artist and title are required"})

            secondary_payload = None
            if secondary is not None:
                if not isinstance(secondary, dict):
                    return self._send_json(400, {"error": "secondary must be an object or null"})
                s_artist = (secondary.get("artist") or "").strip()
                s_title = (secondary.get("title") or "").strip()
                if not s_artist or not s_title:
                    return self._send_json(400, {"error": "secondary.artist and secondary.title are required"})
                secondary_payload = {"artist": s_artist, "title": s_title}

            result = generate_the_mood(
                artist=artist,
                title=title,
                secondary=secondary_payload,
                max_keywords=max_keywords,
                max_scene_sentences=max_scene_sentences,
            )
            return self._send_json(200, result)

        except json.JSONDecodeError:
            return self._send_json(400, {"error": "Invalid JSON"})
        except Exception as e:
            return self._send_json(500, {"error": str(e)})

    def log_message(self, format, *args):
        """Override to reduce log noise."""
        pass


def main():
    """Start the HTTP server."""
    # Avoid "Address already in use" on quick restarts (TIME_WAIT, etc.)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), DjcapHandler) as httpd:
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

