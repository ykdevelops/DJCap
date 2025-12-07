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
import mimetypes
import random
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from src.key_translator import translate_key_to_characteristics

# Configuration
PORT = 8080
OUTPUT_JSON_PATH = Path(__file__).parent.parent / "data" / "output" / "djcap_output.json"
FRONTEND_DIR = Path(__file__).parent
# Local media bank (mp4/gif files)
BANK_DIR = Path("/Users/youssefkhalil/Desktop/bank copy")
MEDIA_PREFIX = "/media/"
# Allow quick restarts without waiting for TIME_WAIT sockets to clear
socketserver.TCPServer.allow_reuse_address = True


class DjcapHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def do_GET(self):
        parsed_path = urlparse(self.path)
        
        # API endpoint for output JSON (now contains all enriched data)
        if parsed_path.path == '/api/enriched':
            self.serve_output_json()
        elif parsed_path.path == '/api/gifs':
            self.serve_gifs(parsed_path)
        elif parsed_path.path.startswith(MEDIA_PREFIX):
            self.serve_media(parsed_path.path[len(MEDIA_PREFIX):])
        else:
            # Serve static files
            super().do_GET()

    def serve_output_json(self):
        """Serve the output JSON file (for activity checks) with CORS headers."""
        try:
            if OUTPUT_JSON_PATH.exists():
                with open(OUTPUT_JSON_PATH, 'r') as f:
                    data = json.load(f)
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
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

    def serve_gifs(self, parsed_path):
        """
        Serve GIFs/videos from the local bank directory. No external API calls.
        """
        try:
            if not OUTPUT_JSON_PATH.exists():
                self.send_response(404)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Output JSON not found'}).encode('utf-8'))
                return

            with open(OUTPUT_JSON_PATH, 'r') as f:
                data = json.load(f)

            query = parse_qs(parsed_path.query)
            deck_param = (query.get('deck', ['active'])[0] or 'active').lower()

            # Determine which deck to use
            deck_name = None
            if deck_param in ('deck1', 'deck2'):
                deck_name = deck_param
            else:
                # Use active flags if present
                deck1_active = data.get('deck1', {}).get('active', False)
                deck2_active = data.get('deck2', {}).get('active', False)
                if deck1_active and not deck2_active:
                    deck_name = 'deck1'
                elif deck2_active and not deck1_active:
                    deck_name = 'deck2'
                elif deck1_active and deck2_active:
                    deck_name = data.get('active_deck', 'deck1')
                else:
                    deck_name = data.get('active_deck', 'deck1')

            deck_data = data.get(deck_name, {})
            title = deck_data.get('title') or ''
            artist = deck_data.get('artist') or ''
            bpm = deck_data.get('bpm')
            key = deck_data.get('key')

            total_limit = int(query.get('limit', ['20'])[0] or 20)
            total_limit = max(1, min(total_limit, 100))

            gifs = self._get_local_gifs(limit=total_limit)

            keywords = []
            if title:
                keywords.append(str(title))
            if artist:
                keywords.append(str(artist))
            keywords.extend(translate_key_to_characteristics(key))

            response = {
                'success': True,
                'deck': deck_name,
                'metadata': {
                    'title': title,
                    'artist': artist,
                    'bpm': bpm,
                    'key': key
                },
                'keywords': keywords,
                'gifs': gifs
            }

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode('utf-8'))
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))

    def log_message(self, format, *args):
        """Override to reduce log noise."""
        pass

    def _get_local_gifs(self, limit: int):
        """
        Return a list of local MP4 assets from BANK_DIR (numbered files only) as dicts with url/title.
        """
        if not BANK_DIR.exists():
            return []
        # Only use numbered mp4 files in the root of BANK_DIR (ignore subfolders like giphy/)
        paths = [p for p in BANK_DIR.glob("*.mp4") if p.name.rstrip(".mp4").isdigit()]
        if not paths:
            return []
        random.shuffle(paths)
        selected = paths[:limit]
        gifs = []
        for p in selected:
            rel = p.relative_to(BANK_DIR)
            gifs.append({
                "id": p.stem,
                "url": f"{MEDIA_PREFIX}{rel.as_posix()}",
                "title": p.stem,
                "mime": mimetypes.guess_type(p.name)[0] or "video/mp4"
            })
        return gifs

    def serve_media(self, rel_path: str):
        """
        Serve a local media file from BANK_DIR at /media/<relative>.
        """
        try:
            bank_resolved = BANK_DIR.resolve()
        except FileNotFoundError:
            bank_resolved = BANK_DIR

        target = (BANK_DIR / rel_path).resolve()
        if not str(target).startswith(str(bank_resolved)):
            self.send_response(403)
            self.end_headers()
            return
        if not target.exists() or not target.is_file():
            self.send_response(404)
            self.end_headers()
            return

        mime, _ = mimetypes.guess_type(target.name)
        mime = mime or "video/mp4"
        try:
            with open(target, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(data)
        except Exception:
            self.send_response(500)
            self.end_headers()


def main():
    """Start the HTTP server."""
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

