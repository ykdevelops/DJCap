# AudioGiphy

[![GitHub](https://img.shields.io/badge/GitHub-Repository-blue)](https://github.com/ykdevelops/AudioGiphy)

AudioGiphy is a real-time DJ metadata capture and visualization system that continuously monitors the djay Pro application window, extracts track metadata (Deck #, Song Title, Artist Name, BPM, Key) using Apple Vision OCR, enriches it with Last.fm tags, downloads music videos from YouTube, and provides a live web-based visualization interface with music videos overlaid with dance videos.

## Features

- **Non-intrusive capture**: Uses Core Graphics API to capture djay Pro window without stealing focus
- **Apple Vision OCR**: Uses native macOS OCR (via `ocrmac`) for accurate text extraction
- **Continuous monitoring**: Updates JSON file every few seconds with real-time track metadata
- **Metadata enrichment**: Automatically enriches tracks with Last.fm tags, keywords, and musical key characteristics
- **Music video integration**: Automatically downloads and plays music videos from YouTube using `yt-dlp`
- **Dance video overlay**: Overlays dance videos from the offline bank on top of music videos, switching every second
- **Proactive downloading**: Proactively downloads music videos for upcoming tracks in inactive decks
- **1-second video clips**: Both music and dance videos are served as 1-second clips with smooth fade in/out effects
- **BPM-synced video playback**: Videos automatically adjust playback rate to match track BPM
- **Cookie-based authentication**: Uses browser cookies with `yt-dlp` to bypass YouTube bot detection
- **Dance video bank**: Integrates offline dance video library (`data/dance_mp4_bank/`) for visual variety
- **Rate limiting**: Smart rate limiting for Giphy API to stay within limits
- **Live web visualization**: Vue.js frontend for real-time visualization of tracks, music videos, and dance overlays
- **Auto-cleanup**: Automatic output folder cleanup to manage file sizes
- **File watching friendly**: JSON file is written atomically for safe file watching
- **Server management**: Convenient scripts to start/stop/restart all services
- **Organized repository**: Scripts organized into `scripts/debug/`, `scripts/analysis/`, and `scripts/utils/` folders

## Requirements

- macOS (uses Apple Vision and Core Graphics APIs)
- Python 3.8+
- djay Pro application running
- `yt-dlp` for music video downloads: `pip install yt-dlp`
- `ffmpeg` for video processing (install via Homebrew: `brew install ffmpeg`)

## Installation

1. Clone or download this repository

2. Install dependencies:
```bash
pip install -r requirements.txt
pip install yt-dlp  # For music video downloads
```

3. Install ffmpeg (required for video processing):
```bash
brew install ffmpeg
```

4. Grant accessibility permissions (required for window detection):
   - Go to System Settings > Privacy & Security > Accessibility
   - Add Terminal (or your terminal app) and enable it
   - This allows the script to detect the djay Pro window

## Project Structure

```
AudioGiphy/
├── src/                    # Core modules
│   ├── window_capture.py   # Window capture functionality
│   ├── metadata_extractor.py  # OCR and metadata extraction
│   ├── config.py           # Configuration and API keys
│   ├── gif_bank.py         # GIF bank management
│   ├── dance_video_bank.py # Dance video bank management
│   ├── key_translator.py   # Musical key translation
│   └── output_cleanup.py   # Output folder cleanup utilities
├── tools/                  # Utility scripts
│   ├── define_regions.py   # Interactive region definition tool
│   ├── define_play_buttons.py  # Play button calibration
│   └── save_all_regions.py # Save region screenshots
├── frontend/               # Web frontend
│   ├── server.py          # Frontend web server
│   ├── index.html         # Main visualization page
│   └── viewer.html        # Alternative viewer
├── scripts/                # Utility scripts (organized by purpose)
│   ├── debug/             # Debug scripts and test images
│   │   ├── debug_green_color.py
│   │   ├── debug_play_button.py
│   │   └── [other debug scripts]
│   ├── analysis/          # Analysis scripts
│   │   ├── analyze_video_repetitions.py
│   │   └── analyze_video_similarities.py
│   └── utils/             # Utility scripts
│       ├── cleanup.py      # Cleanup script (Python)
│       ├── cleanup.sh      # Cleanup script (Bash)
│       ├── start_servers.sh    # Start all services
│       ├── stop_servers.sh     # Stop all services
│       └── restart_servers.sh  # Restart all services
├── data/                   # Data files
│   ├── region_coordinates.json  # OCR region coordinates
│   ├── gif_bank/          # GIF bank storage
│   ├── dance_mp4_bank/    # Dance video bank (MP4 files)
│   ├── music_videos/      # Downloaded music videos (MP4 files)
│   └── output/            # Output JSON files
│       ├── djcap_output.json
│       ├── giphy_history.json
│       └── giphy_rate_state.json
├── djcap.py               # Main capture service
├── djcap_processor.py     # Metadata enrichment service
└── requirements.txt       # Python dependencies
```

**Note:** Scripts are organized into `scripts/` subdirectories:
- `scripts/debug/` - Debug and testing scripts
- `scripts/analysis/` - Video analysis and processing scripts
- `scripts/utils/` - Utility scripts (cleanup, server management)

## Usage

### Quick Start (All Services)

Use the convenience scripts to manage all services:

```bash
# Start all services (djcap, processor, frontend)
./scripts/utils/start_servers.sh

# Stop all services
./scripts/utils/stop_servers.sh

# Restart all services
./scripts/utils/restart_servers.sh
```

### Manual Start

Run services individually:

1. **Capture service** (captures metadata from djay Pro):
```bash
python djcap.py
```

2. **Processor service** (enriches metadata with GIFs and videos):
```bash
python djcap_processor.py
```

3. **Frontend server** (web visualization):
```bash
python frontend/server.py
```

The capture script will:
- Continuously capture the djay Pro window every 3 seconds
- Extract metadata from both decks
- Save results to `data/output/djcap_output.json`

Press `Ctrl+C` to stop individual services.

## Output Format

The JSON file (`data/output/djcap_output.json`) contains:

```json
{
  "deck1": {
    "deck": "deck1",
    "title": "Song Title",
    "artist": "Artist Name",
    "bpm": 128,
    "key": "1A"
  },
  "deck2": {
    "deck": "deck2",
    "title": "Another Song",
    "artist": "Another Artist",
    "bpm": 130,
    "key": "2B"
  },
  "active_deck": "deck1",
  "timestamp": "2024-12-04T20:30:45.123456",
  "last_updated": 1701724245.123456
}
```

## Metadata Processor (djcap_processor.py)

The metadata processor service watches `djcap_output.json` for changes and enriches the metadata with:

- **Last.fm tags**: Fetches genre, mood, and context tags for tracks
- **Keyword analysis**: Analyzes and selects the best keywords from metadata and tags
- **Music video downloads**: Automatically downloads music videos from YouTube using `yt-dlp` with cookie-based authentication
- **Dance video overlay**: Fetches 60 dance video clips from the offline bank for overlay on music videos
- **Proactive downloading**: Downloads music videos for upcoming tracks in inactive decks before they become active

### Setup

1. Configure API keys (create `.env` file or set environment variables):
```bash
LASTFM_API_KEY=your_lastfm_api_key
GIPHY_API_KEY=your_giphy_api_key
GOOGLE_API_KEY=your_google_api_key
GOOGLE_CSE_ID=your_google_custom_search_engine_id
```

**Google Custom Search Setup:**
- Go to [Google Cloud Console](https://console.cloud.google.com/) and create a project
- Enable the "Custom Search API"
- Create an API key in "APIs & Services" > "Credentials"
- Go to [Programmable Search Engine](https://cse.google.com/cse/all) and create a new search engine
- Set it to "Search the entire web" and enable "Image search"
- Copy the Search Engine ID (cx parameter)
- Add both `GOOGLE_API_KEY` and `GOOGLE_CSE_ID` to your `.env` file

Alternatively, the processor will try to use API keys from AudioApis if available.

Optional tuning (safe defaults):

```bash
# Hard cap on live Giphy requests per rolling hour (persisted across restarts)
GIPHY_MAX_REQUESTS_PER_HOUR=40

# Pool size fetched per track (still a single request). UI shows 5 at a time.
GIPHY_FETCH_POOL_SIZE=25

# How many GIF IDs to remember per artist to reduce repeats across tracks
GIPHY_HISTORY_MAX_IDS_PER_ARTIST=200
```

2. Run the processor:
```bash
python djcap_processor.py
```

The processor will:
- Monitor `data/output/djcap_output.json` for changes
- Enrich active decks (where `active: true`) with Last.fm tags, keywords, and GIFs
- Write enriched data directly back to `data/output/djcap_output.json`
- Inactive decks keep only basic metadata (title, artist, BPM, key, active)

### Music Video & Dance Overlay System

- **Music Video Downloads**:
  - Automatically downloads music videos from YouTube using `yt-dlp`
  - Uses browser cookies for authentication to bypass bot detection
  - Videos are processed into 1-second clips with fade in/out effects
  - Stored in `data/music_videos/` directory
  - Proactively downloads videos for upcoming tracks in inactive decks

- **Dance Video Overlay**:
  - 60 dance video clips are fetched from `data/dance_mp4_bank/` for each track
  - Each dance video generates 3 unique 1-second clips (at 0s, 1s, 2s) with fade effects
  - Overlay appears on top of music video with higher z-index (z-index: 10)
  - Switches to a new dance video every second while music video plays continuously
  - Overlay stays visible and cycles through videos automatically

- **Video Processing**:
  - All videos (music and dance) are served as 1-second clips on-the-fly
  - Fade in/out effects applied using `ffmpeg` filters
  - Minimum bitrate and keyframe intervals ensure valid MP4 files
  - Videos are streamed directly from the server without pre-generating files

- **BPM Sync**: Music videos automatically adjust playback rate to match track BPM (rate = BPM / 120)

### GIF behavior (safe defaults)

- **Search query**: 
  - **Giphy**: artist-only (broad and consistent)
  - **Google**: "artist [ArtistName] [SongTitle] music video" (more specific)
- **GIF sources**: 
  - **Primary**: Giphy API (fetches up to 5-10 GIFs depending on Google availability)
  - **Secondary**: Google Custom Search API (fetches 5 GIFs if API key is configured)
- **Video pool**: 5 videos per track from dance video bank (increases to 15 if GIFs unavailable)
- **Pool**: a larger per-track pool (`gif_pool`) is fetched once per track so the UI can replace disliked GIFs without extra API calls
- **Rate limiting**: live Giphy calls are capped per rolling hour (default: 40/hour); state is saved to `data/output/giphy_rate_state.json`
- **Repeat avoidance**: recently used GIF IDs are tracked per artist in `data/output/giphy_history.json`
- **Fallback behavior**: If GIFs are unavailable (rate limited or API errors), the system automatically uses more videos to maintain the 15-item rotation

### Output Format

The JSON file (`data/output/djcap_output.json`) contains:

```json
{
  "deck1": {
    "deck": "deck1",
    "title": "Song Title",
    "artist": "Artist Name",
    "bpm": 128,
    "key": "1A",
    "active": true,
    "lastfm_tags": ["electronic", "dance", "energetic"],
    "refined_keywords": ["Song Title", "Artist Name", "electronic", "dance", "innocent", "pure"],
    "keyword_scores": {
      "electronic": 0.95,
      "dance": 0.88
    },
    "key_characteristics": ["innocent", "pure", "simple", "happy"],
    "giphy_query": "Artist Name",
    "giphy_query_parts": ["Artist Name"],
    "gifs": [...],
    "gif_pool": [...],
    "dance_videos_overlay": [...],  # 60 dance video clips for overlay
    "music_video": "/api/music_video/Artist - Title.mp4",  # Music video URL
    "music_video_status": "ready",  # Status: "ready", "downloading", "error", or "empty"
    "music_video_clips": [...]  # 1-second clips with fade effects
  },
  "deck2": {
    "deck": "deck2",
    "title": "Another Song",
    "artist": "Another Artist",
    "bpm": 130,
    "key": "2B",
    "active": false
  },
  "active_deck": "deck1",
  "timestamp": "2024-12-04T20:30:45.123456",
  "last_updated": 1701724245.123456
}
```

**Note:** Only active decks (`active: true`) are enriched with `lastfm_tags`, `refined_keywords`, `keyword_scores`, `key_characteristics`, `gifs`, and `gif_pool`. Inactive decks contain only basic metadata.

## File Watching

Other applications can watch the JSON file for changes using:

- **Python**: `watchdog` library
- **Node.js**: `chokidar` or `fs.watch`
- **macOS**: `fswatch` command-line tool
- **Native**: File system events APIs

The file is written atomically (via temp file + rename) to prevent reading partial writes.

## Configuration

Edit `djcap.py` to change:

- `UPDATE_INTERVAL`: Seconds between updates (default: 3)
- `OUTPUT_FILE`: Path to JSON output file (default: "data/output/djcap_output.json")

Edit `djcap_processor.py` to change:

- `DJCAP_JSON_FILE`: Path to JSON file to watch and enrich (default: "data/output/djcap_output.json")

## Troubleshooting

### "djay Pro window not found"
- Ensure djay Pro is running
- Check that accessibility permissions are granted
- Try restarting djay Pro

### "ocrmac not available"
- Install ocrmac: `pip install ocrmac`
- Ensure you're on macOS (ocrmac requires macOS)

### Music video not downloading
- Ensure `yt-dlp` is installed: `pip install yt-dlp`
- Ensure `ffmpeg` is installed: `brew install ffmpeg`
- Check backend logs for `yt-dlp` errors (may need browser cookies for authentication)
- Music videos are downloaded proactively for inactive decks, so they may take time to appear

### Dance overlay not visible
- Ensure both music video and dance videos are available (check console logs)
- Verify z-index is set correctly (dance overlay should have z-index: 10)
- Check browser console for any CSS or JavaScript errors
- Hard refresh browser (Cmd+Shift+R) to clear cached JavaScript

### Active deck not detected / decks appear inactive
- The play-button detector looks for the neon green outline around each deck play button. If your resolution/layout changes, recalibrate with `tools/define_play_buttons.py` to update `data/region_coordinates.json` (`deck1_play_button` / `deck2_play_button`).
- After recalibration, restart `djcap.py` (and the frontend if running) so the new coordinates are picked up.
- Both decks can be `active: true` if both are playing; `active_deck` is the primary display deck used by clients when needed.

### Frontend API notes
- The frontend server exposes:
  - **`GET /api/enriched`** - Serves `data/output/djcap_output.json` with ETag support for conditional requests
  - **`GET /api/dance_video/{filename}?start={seconds}`** - Serves 1-second MP4 clips from `data/dance_mp4_bank/` with fade effects (on-the-fly processing)
  - **`GET /api/music_video/{filename}`** - Serves music video files from `data/music_videos/`
  - Static HTML files (index.html, viewer.html)
- UI assets are served with **no-cache** headers to make local development updates show immediately.
- Dance videos are processed on-the-fly using `ffmpeg` to extract 1-second segments with fade in/out effects

### Poor OCR accuracy
- Ensure djay Pro window is visible (not minimized)
- Check that the window size is reasonable (not too small)
- The coordinates are calibrated for standard djay Pro layouts

## Maintenance

### Cleaning Up Generated Data

The project generates various temporary files (debug images, output JSONs, etc.) that should not be committed to Git. Run the cleanup script regularly to remove unnecessary files:

**Using Python (recommended):**
```bash
python scripts/utils/cleanup.py
```

**Using Bash:**
```bash
./scripts/utils/cleanup.sh
```

This will remove:
- All PNG/JPG images from `scripts/debug/` folder
- Temporary files (`.tmp`, `.bak`, `.swp`, `*~`)
- Python cache files (`__pycache__/`, `*.pyc`, `*.pyo`)
- Any images in the root directory

**Note:** Output JSON files in `data/output/` are NOT removed by default as they are needed for the application to function. If you want to remove them, do so manually.

**Recommendation:** Run cleanup regularly (e.g., weekly) or before committing to Git to keep the repository clean.

### Git Ignore

The following are automatically ignored by Git:
- All image files (`.png`, `.jpg`, `.jpeg`, etc.)
- `scripts/debug/` folder (contains test images and debug scripts)
- `data/output/` folder (contains generated JSON files)
- Temporary files and Python cache

## Frontend Visualization

A Vue.js frontend is available to visualize the enriched metadata and GIFs in real-time.

### Running the Frontend

1. Start the frontend server:
```bash
python frontend/server.py
```

2. Open your browser and navigate to:
```
http://localhost:8080
```

The frontend will:
- Display current track metadata (title, artist, BPM, key)
- Show Last.fm tags and refined keywords
- Display 5 GIFs (`gifs`) and allow replacing individual GIFs from the per-track `gif_pool`
- Auto-refresh every 2 seconds to show live updates

### Frontend Features

- **Real-time Updates**: Automatically polls for new data every 2 seconds
- **Track Information**: Shows title, artist, BPM, and key
- **Tags & Keywords**: Displays Last.fm tags and refined keywords
- **Music Video Display**: Shows downloaded music videos as the base layer
- **Dance Video Overlay**: Overlays dance videos on top of music videos, switching every second
- **BPM-synced Playback**: Music videos automatically adjust playback speed to match track BPM
- **Video Duration**: Fixed 1-second clips for dance overlays with smooth fade transitions
- **Continuous Playback**: Music video plays continuously while dance overlay cycles through videos
- **Z-index Management**: Dance overlay uses z-index: 10 to ensure it appears above music video
- **Auto-start**: Overlay automatically starts when both music video and dance videos are available
- **Responsive Design**: Works on desktop and mobile devices

## License

This project uses code adapted from AudioApis for window capture functionality.

