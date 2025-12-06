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

# Add AudioApis to path so we can reuse its Giphy client
AUDIOAPIS_PATH = "/Users/youssefkhalil/AudioApis"
if os.path.exists(AUDIOAPIS_PATH):
    sys.path.insert(0, AUDIOAPIS_PATH)
    try:
        from metadata.giphy_client import fetch_gifs_for_keywords
    except Exception:
        fetch_gifs_for_keywords = None
else:
    fetch_gifs_for_keywords = None

from src.key_translator import translate_key_to_characteristics

# Configuration
PORT = 8080
OUTPUT_JSON_PATH = Path(__file__).parent.parent / "data" / "output" / "djcap_output.json"
FRONTEND_DIR = Path(__file__).parent
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
        Serve GIFs for the current deck by calling Giphy directly using deck data.
        This ignores any pre-enriched GIFs and uses only the basic deck metadata:
        title, artist, key (translated to characteristics).
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

            # Build keywords: only the default tag, title, and artist
            keywords = ['#dance']
            if title:
                keywords.append(str(title))
            if artist:
                keywords.append(str(artist))

            # Total limit and per-keyword limit
            total_limit = int(query.get('limit', ['20'])[0] or 20)
            total_limit = max(1, min(total_limit, 100))

            gifs = []
            used_keywords = keywords

            if fetch_gifs_for_keywords and keywords:
                per_keyword = max(1, total_limit // max(1, len(keywords)))
                try:
                    gifs = fetch_gifs_for_keywords(keywords, limit_per_keyword=per_keyword)
                except Exception as e:
                    gifs = []
            else:
                used_keywords = []

            # Trim to total_limit
            gifs = gifs[:total_limit]

            response = {
                'success': True,
                'deck': deck_name,
                'metadata': {
                    'title': title,
                    'artist': artist,
                    'bpm': bpm,
                    'key': key
                },
                'keywords': used_keywords,
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

