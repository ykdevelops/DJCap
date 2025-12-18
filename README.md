# DjCap

DjCap is a tool that continuously captures the djay Pro application window, extracts track metadata (Deck #, Song Title, Artist Name, BPM, Key) using Apple Vision OCR, and saves it to a JSON file that other applications can monitor.

## Features

- **Non-intrusive capture**: Uses Core Graphics API to capture djay Pro window without stealing focus
- **Apple Vision OCR**: Uses native macOS OCR (via `ocrmac`) for accurate text extraction
- **Continuous monitoring**: Updates JSON file every few seconds
- **File watching friendly**: JSON file is written atomically for safe file watching

## Requirements

- macOS (uses Apple Vision and Core Graphics APIs)
- Python 3.8+
- djay Pro application running

## Installation

1. Clone or download this repository

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Grant accessibility permissions (required for window detection):
   - Go to System Settings > Privacy & Security > Accessibility
   - Add Terminal (or your terminal app) and enable it
   - This allows the script to detect the djay Pro window

## Project Structure

```
DjCap/
├── src/                    # Core modules
│   ├── window_capture.py   # Window capture functionality
│   ├── metadata_extractor.py  # OCR and metadata extraction
│   └── config.py           # Configuration and API keys
├── tools/                  # Utility scripts
│   ├── define_regions.py   # Interactive region definition tool
│   └── save_all_regions.py # Save region screenshots
├── debug/                  # Debug scripts and test images
├── data/                   # Data files
│   ├── region_coordinates.json  # OCR region coordinates
│   └── output/            # Output JSON files
│       ├── djcap_output.json
│       └── djcap_enriched.json
├── djcap.py               # Main capture service
├── djcap_processor.py     # Metadata enrichment service
└── requirements.txt       # Python dependencies
```

## Usage

Run the main capture script:

```bash
python djcap.py
```

The script will:
- Continuously capture the djay Pro window every 3 seconds
- Extract metadata from both decks
- Save results to `data/output/djcap_output.json`

Press `Ctrl+C` to stop.

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
- **GIF search**: Fetches relevant GIFs based on refined keywords

### Setup

1. Configure API keys (create `.env` file or set environment variables):
```bash
LASTFM_API_KEY=your_lastfm_api_key
GIPHY_API_KEY=your_giphy_api_key
```

Alternatively, the processor will try to use API keys from AudioApis if available.

2. Run the processor:
```bash
python djcap_processor.py
```

The processor will:
- Monitor `data/output/djcap_output.json` for changes
- Enrich active decks (where `active: true`) with Last.fm tags, keywords, and GIFs
- Write enriched data directly back to `data/output/djcap_output.json`
- Inactive decks keep only basic metadata (title, artist, BPM, key, active)

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
    "gifs": [...]
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

**Note:** Only active decks (`active: true`) are enriched with `lastfm_tags`, `refined_keywords`, `keyword_scores`, `key_characteristics`, and `gifs`. Inactive decks contain only basic metadata.

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

### Active deck not detected / decks appear inactive
- The play-button detector looks for the neon green outline around each deck play button. If your resolution/layout changes, recalibrate with `tools/define_play_buttons.py` to update `data/region_coordinates.json` (`deck1_play_button` / `deck2_play_button`).
- After recalibration, restart `djcap.py` (and the frontend if running) so the new coordinates are picked up.
- Both decks can be `active: true` if both are playing; `active_deck` is the primary display deck used by clients when needed.

### `/api/theMood` errors (frontend)
- The frontend server exposes:
  - `GET /api/theMood`: lightweight “current mood” derived from the active deck’s enriched fields (no OpenAI calls).
  - `POST /api/theMood`: Wikipedia-grounded theMood generation (requires OpenAI).
- For `POST /api/theMood`, set `OPENAI_API_KEY` in the repo root `.env` (recommended) or export it in your shell.

### Poor OCR accuracy
- Ensure djay Pro window is visible (not minimized)
- Check that the window size is reasonable (not too small)
- The coordinates are calibrated for standard djay Pro layouts

## Maintenance

### Cleaning Up Generated Data

The project generates various temporary files (debug images, output JSONs, etc.) that should not be committed to Git. Run the cleanup script regularly to remove unnecessary files:

**Using Python (recommended):**
```bash
python cleanup.py
```

**Using Bash:**
```bash
./cleanup.sh
```

This will remove:
- All PNG/JPG images from `debug/` folder
- Temporary files (`.tmp`, `.bak`, `.swp`, `*~`)
- Python cache files (`__pycache__/`, `*.pyc`, `*.pyo`)
- Any images in the root directory

**Note:** Output JSON files in `data/output/` are NOT removed by default as they are needed for the application to function. If you want to remove them, do so manually.

**Recommendation:** Run cleanup regularly (e.g., weekly) or before committing to Git to keep the repository clean.

### Git Ignore

The following are automatically ignored by Git:
- All image files (`.png`, `.jpg`, `.jpeg`, etc.)
- `debug/` folder (contains test images and debug scripts)
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
- Display GIFs fetched based on the keywords
- Auto-refresh every 2 seconds to show live updates

### Frontend Features

- **Real-time Updates**: Automatically polls for new data every 2 seconds
- **Track Information**: Shows title, artist, BPM, and key
- **Tags & Keywords**: Displays Last.fm tags and refined keywords
- **GIF Gallery**: Shows all GIFs fetched for the current track
- **Responsive Design**: Works on desktop and mobile devices

## License

This project uses code adapted from AudioApis for window capture functionality.

