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
        """Serve dance video files from the dance_mp4_bank folder, with trimming support for repeated segments."""
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
            
            # Check for trim information (if video has repeated segments)
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

