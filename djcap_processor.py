#!/usr/bin/env python3
"""
DjCap JSON Watcher and Metadata Processor
Monitors djcap_output.json for changes and enriches metadata with Last.fm tags,
keyword analysis, and GIFs.
"""
import json
import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
import os

# Add AudioApis to Python path
AUDIOAPIS_PATH = '/Users/youssefkhalil/AudioApis'
if os.path.exists(AUDIOAPIS_PATH):
    sys.path.insert(0, AUDIOAPIS_PATH)

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileModifiedEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    logging.warning("watchdog not available. Install with: pip install watchdog")

# Import AudioApis metadata modules
try:
    from metadata.lastfm_client import get_lastfm_tags
    from metadata.keyword_analyzer import analyze_keywords
    from metadata.giphy_client import fetch_gifs_for_keywords
    METADATA_MODULES_AVAILABLE = True
except ImportError as e:
    METADATA_MODULES_AVAILABLE = False
    logging.warning(f"AudioApis metadata modules not available: {e}")

from src.config import LASTFM_API_KEY, GIPHY_API_KEY

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
DJCAP_JSON_FILE = "/Users/youssefkhalil/DjCap/data/output/djcap_output.json"
ENRICHED_JSON_FILE = "/Users/youssefkhalil/DjCap/data/output/djcap_enriched.json"
DEBOUNCE_DELAY = 0.1  # seconds to wait after file change before processing
RUNNING = True

# Track last processed file to avoid duplicates
_last_processed_time = 0
_last_processed_content = None


def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully."""
    global RUNNING
    logger.info("Received interrupt signal, shutting down...")
    RUNNING = False
    sys.exit(0)


def read_djcap_json(file_path: str, max_retries: int = 5, retry_delay: float = 0.1) -> Optional[Dict[str, Any]]:
    """
    Safely read JSON file, handling atomic writes.
    
    Args:
        file_path: Path to JSON file
        max_retries: Maximum number of retries if file is locked
        retry_delay: Delay between retries in seconds
        
    Returns:
        Parsed JSON dictionary or None if read fails
    """
    temp_file = f"{file_path}.tmp"
    
    for attempt in range(max_retries):
        try:
            # Check if temp file exists (atomic write in progress)
            if os.path.exists(temp_file):
                time.sleep(retry_delay)
                continue
            
            # Read the JSON file
            with open(file_path, 'r') as f:
                content = f.read().strip()
                if not content:
                    logger.debug("JSON file is empty")
                    return None
                
                data = json.loads(content)
                return data
                
        except json.JSONDecodeError as e:
            logger.warning(f"JSON decode error (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                logger.error(f"Failed to read JSON after {max_retries} attempts")
                return None
                
        except FileNotFoundError:
            logger.warning(f"JSON file not found: {file_path}")
            return None
            
        except Exception as e:
            logger.error(f"Error reading JSON file: {e}", exc_info=True)
            return None
    
    return None


def extract_active_deck_metadata(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract metadata from the active deck.
    
    Args:
        data: Full JSON data from djcap_output.json
        
    Returns:
        Dictionary with title, artist, bpm, key or None if active deck not found
    """
    active_deck = data.get('active_deck')
    if not active_deck:
        logger.warning("No active_deck specified in JSON")
        return None
    
    deck_data = data.get(active_deck)
    if not deck_data:
        logger.warning(f"Active deck '{active_deck}' not found in JSON")
        return None
    
    metadata = {
        'title': deck_data.get('title'),
        'artist': deck_data.get('artist'),
        'bpm': deck_data.get('bpm'),
        'key': deck_data.get('key')
    }
    
    return metadata


def enrich_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enrich metadata with Last.fm tags, keywords, and GIFs.
    
    Args:
        metadata: Dictionary with title, artist, bpm, key
        
    Returns:
        Enriched metadata dictionary
    """
    title = metadata.get('title')
    artist = metadata.get('artist')
    bpm = metadata.get('bpm')
    key = metadata.get('key')
    
    enriched = {
        'metadata': metadata.copy(),
        'lastfm_tags': [],
        'refined_keywords': [],
        'keyword_scores': {},
        'gifs': []
    }
    
    # Get Last.fm tags
    if METADATA_MODULES_AVAILABLE and LASTFM_API_KEY and artist and title:
        try:
            logger.info(f"Fetching Last.fm tags for: {artist} - {title}")
            lastfm_tags = get_lastfm_tags(artist, title)
            enriched['lastfm_tags'] = lastfm_tags
            logger.info(f"Got {len(lastfm_tags)} Last.fm tags: {lastfm_tags}")
        except Exception as e:
            logger.error(f"Error fetching Last.fm tags: {e}", exc_info=True)
    else:
        if not METADATA_MODULES_AVAILABLE:
            logger.warning("Metadata modules not available, skipping Last.fm")
        elif not LASTFM_API_KEY:
            logger.warning("Last.fm API key not configured")
        elif not artist or not title:
            logger.warning("Missing artist or title for Last.fm lookup")
    
    # Analyze keywords
    if METADATA_MODULES_AVAILABLE:
        try:
            ocr_metadata = {
                'title': title,
                'artist': artist,
                'bpm': bpm,
                'key': key
            }
            logger.info("Analyzing keywords...")
            result = analyze_keywords(
                ocr_metadata=ocr_metadata,
                lastfm_tags=enriched['lastfm_tags'],
                bpm=bpm,
                key=key
            )
            # analyze_keywords returns a tuple: (keywords, scores)
            if isinstance(result, tuple) and len(result) == 2:
                keywords, scores = result
            else:
                # Fallback if return format is different
                keywords = result if isinstance(result, list) else []
                scores = {}
            enriched['refined_keywords'] = keywords
            enriched['keyword_scores'] = scores
            logger.info(f"Selected keywords: {keywords} (scores: {scores})")
        except Exception as e:
            logger.error(f"Error analyzing keywords: {e}", exc_info=True)
    else:
        logger.warning("Metadata modules not available, skipping keyword analysis")
    
    # Fetch GIFs
    if METADATA_MODULES_AVAILABLE and GIPHY_API_KEY and enriched['refined_keywords']:
        try:
            logger.info(f"Fetching GIFs for keywords: {enriched['refined_keywords']}")
            gifs = fetch_gifs_for_keywords(enriched['refined_keywords'], limit_per_keyword=1)
            enriched['gifs'] = gifs
            logger.info(f"Fetched {len(gifs)} GIFs")
        except Exception as e:
            logger.error(f"Error fetching GIFs: {e}", exc_info=True)
    else:
        if not METADATA_MODULES_AVAILABLE:
            logger.warning("Metadata modules not available, skipping GIF fetch")
        elif not GIPHY_API_KEY:
            logger.warning("Giphy API key not configured")
        elif not enriched['refined_keywords']:
            logger.warning("No keywords available for GIF search")
    
    return enriched


def save_enriched_json(enriched_data: Dict[str, Any], output_file: str):
    """
    Save enriched metadata to JSON file atomically.
    
    Args:
        enriched_data: Enriched metadata dictionary
        output_file: Path to output JSON file
    """
    try:
        # Add timestamp
        enriched_data["timestamp"] = datetime.now().isoformat()
        enriched_data["last_updated"] = time.time()
        
        # Write to temp file first, then rename (atomic write)
        temp_file = f"{output_file}.tmp"
        with open(temp_file, 'w') as f:
            json.dump(enriched_data, f, indent=2, ensure_ascii=False)
        
        # Atomic rename
        Path(temp_file).rename(output_file)
        
        logger.debug(f"Enriched metadata saved to {output_file}")
        
    except Exception as e:
        logger.error(f"Failed to save enriched metadata: {e}", exc_info=True)


def process_metadata_update(file_path: str):
    """
    Process metadata update when JSON file changes.
    
    Args:
        file_path: Path to the JSON file that changed
    """
    global _last_processed_time, _last_processed_content
    
    # Debounce: check if we recently processed this file
    current_time = time.time()
    if current_time - _last_processed_time < DEBOUNCE_DELAY:
        return
    
    # Read JSON file
    data = read_djcap_json(file_path)
    if not data:
        logger.warning("Failed to read JSON file")
        return
    
    # Check if content actually changed
    content_str = json.dumps(data, sort_keys=True)
    if content_str == _last_processed_content:
        logger.debug("Content unchanged, skipping processing")
        return
    
    _last_processed_time = current_time
    _last_processed_content = content_str
    
    logger.info("Processing metadata update...")
    
    # Extract active deck metadata
    active_deck = data.get('active_deck', 'deck1')
    metadata = extract_active_deck_metadata(data)
    
    if not metadata:
        logger.warning("Could not extract active deck metadata")
        return
    
    logger.info(f"Active deck: {active_deck}, Metadata: {metadata}")
    
    # Enrich metadata
    enriched = enrich_metadata(metadata)
    enriched['active_deck'] = active_deck
    
    # Save enriched JSON
    save_enriched_json(enriched, ENRICHED_JSON_FILE)
    
    logger.info("Metadata enrichment complete")


class DjcapJsonHandler(FileSystemEventHandler):
    """File system event handler for djcap_output.json changes."""
    
    def on_modified(self, event):
        """Handle file modification events."""
        if event.is_directory:
            return
        
        # Only process djcap_output.json
        if event.src_path == DJCAP_JSON_FILE:
            logger.debug(f"File modified: {event.src_path}")
            # Use a small delay to ensure file write is complete
            time.sleep(0.05)
            process_metadata_update(event.src_path)


def main():
    """Main function to start the file watcher."""
    global RUNNING
    
    if not WATCHDOG_AVAILABLE:
        logger.error("watchdog library not available. Please install it: pip install watchdog")
        sys.exit(1)
    
    if not METADATA_MODULES_AVAILABLE:
        logger.warning("AudioApis metadata modules not available. Some features will be disabled.")
        logger.warning(f"Make sure AudioApis is available at: {AUDIOAPIS_PATH}")
    
    # Register signal handler
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("DjCap Metadata Processor starting...")
    logger.info(f"Watching: {DJCAP_JSON_FILE}")
    logger.info(f"Output: {ENRICHED_JSON_FILE}")
    
    # Check if input file exists
    if not os.path.exists(DJCAP_JSON_FILE):
        logger.warning(f"Input file does not exist: {DJCAP_JSON_FILE}")
        logger.info("Waiting for file to be created...")
    
    # Create file watcher
    event_handler = DjcapJsonHandler()
    observer = Observer()
    observer.schedule(event_handler, path=os.path.dirname(DJCAP_JSON_FILE), recursive=False)
    observer.start()
    
    logger.info("File watcher started. Press Ctrl+C to stop.")
    
    # Process initial file if it exists
    if os.path.exists(DJCAP_JSON_FILE):
        logger.info("Processing initial file...")
        process_metadata_update(DJCAP_JSON_FILE)
    
    # Keep running
    try:
        while RUNNING:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    finally:
        observer.stop()
        observer.join()
        logger.info("DjCap Metadata Processor stopped.")


if __name__ == "__main__":
    main()

