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
OUTPUT_JSON_PATH = Path(__file__).parent.parent / "data" / "output" / "djcap_output.json"
FRONTEND_DIR = Path(__file__).parent


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

    def serve_dance_video(self, filename: str):
        """Serve dance video files from the dance_mp4_bank folder."""
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
            
            # Serve the video file
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

