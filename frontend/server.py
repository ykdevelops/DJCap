#!/usr/bin/env python3
"""
Simple HTTP server for DjCap frontend.
Serves the Vue.js frontend and provides API endpoint for enriched JSON data.
"""
import http.server
import socketserver
import json
import os
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Configuration
PORT = 8080
ENRICHED_JSON_PATH = Path(__file__).parent.parent / "data" / "output" / "djcap_enriched.json"
FRONTEND_DIR = Path(__file__).parent


class DjcapHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def do_GET(self):
        parsed_path = urlparse(self.path)
        
        # API endpoint for enriched JSON
        if parsed_path.path == '/api/enriched':
            self.serve_enriched_json()
        else:
            # Serve static files
            super().do_GET()

    def serve_enriched_json(self):
        """Serve the enriched JSON file with CORS headers."""
        try:
            if ENRICHED_JSON_PATH.exists():
                with open(ENRICHED_JSON_PATH, 'r') as f:
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
                self.wfile.write(json.dumps({'error': 'Enriched JSON not found'}).encode('utf-8'))
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
        print(f"Reading enriched JSON from: {ENRICHED_JSON_PATH}")
        print(f"=" * 50)
        print(f"Press Ctrl+C to stop")
        print()
        
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n\nServer stopped.")


if __name__ == "__main__":
    main()

