# DjCap Frontend

Vue.js frontend for visualizing DjCap enriched metadata and GIFs in real-time.

## Features

- **Real-time Updates**: Automatically polls for new track data every 2 seconds
- **Track Information**: Displays title, artist, BPM, and key
- **Last.fm Tags**: Shows genre, mood, and context tags
- **Keywords**: Displays refined keywords used for GIF search
- **GIF Gallery**: Shows all GIFs fetched for the current track
- **Responsive Design**: Works on desktop and mobile devices

## Usage

1. Make sure `djcap.py` and `djcap_processor.py` are running

2. Start the frontend server:
```bash
python frontend/server.py
```

3. Open your browser and navigate to:
```
http://localhost:8080
```

The frontend will automatically connect and start displaying data.

## Architecture

- **index.html**: Single-page Vue.js application (using CDN)
- **server.py**: Simple HTTP server that:
  - Serves the frontend HTML/CSS/JS
  - Provides `/api/enriched` endpoint for JSON data
  - Reads from `data/output/djcap_output.json` (single source of truth)

## API Endpoint

- `GET /api/enriched`: Returns the enriched JSON data with metadata, tags, keywords, and GIFs

## Customization

Edit `index.html` to customize:
- Colors and styling
- Update frequency (change polling interval)
- Layout and components
- Additional features

