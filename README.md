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

## Usage

Run the main script:

```bash
python djcap.py
```

The script will:
- Continuously capture the djay Pro window every 3 seconds
- Extract metadata from both decks
- Save results to `djcap_output.json`

Press `Ctrl+C` to stop.

## Output Format

The JSON file (`djcap_output.json`) contains:

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
- `OUTPUT_FILE`: Path to JSON output file (default: "djcap_output.json")

## Troubleshooting

### "djay Pro window not found"
- Ensure djay Pro is running
- Check that accessibility permissions are granted
- Try restarting djay Pro

### "ocrmac not available"
- Install ocrmac: `pip install ocrmac`
- Ensure you're on macOS (ocrmac requires macOS)

### Poor OCR accuracy
- Ensure djay Pro window is visible (not minimized)
- Check that the window size is reasonable (not too small)
- The coordinates are calibrated for standard djay Pro layouts

## License

This project uses code adapted from AudioApis for window capture functionality.

