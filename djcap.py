#!/usr/bin/env python3
"""
DjCap - djay Pro Capture and Analysis
Continuously captures djay Pro window, extracts metadata, and saves to JSON.
"""
import time
import json
import logging
import signal
import sys
from datetime import datetime
from pathlib import Path
from src.window_capture import capture_djay_window, DjayProWindowNotFoundError
from src.metadata_extractor import extract_metadata

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
UPDATE_INTERVAL = 3  # seconds between updates
OUTPUT_FILE = "data/output/djcap_output.json"  # JSON file for other applications to read
RUNNING = True


def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully."""
    global RUNNING
    logger.info("Received interrupt signal, shutting down...")
    RUNNING = False
    sys.exit(0)


def save_metadata_to_json(metadata: dict, output_file: str):
    """
    Save metadata to JSON file, preserving existing enriched data.
    
    Args:
        metadata: Dictionary with deck1, deck2, active_deck, and timestamp
        output_file: Path to JSON file
    """
    try:
        # Preserve existing enriched data if file exists
        existing_data = {}
        if Path(output_file).exists():
            try:
                with open(output_file, 'r') as f:
                    existing_content = f.read().strip()
                    if existing_content:
                        existing_data = json.loads(existing_content)
            except (json.JSONDecodeError, FileNotFoundError):
                pass  # If file is corrupted or doesn't exist, start fresh
        
        # Merge: preserve enriched fields from existing data
        # Only update basic metadata fields (title, artist, bpm, key, active)
        for deck_name in ['deck1', 'deck2']:
            if deck_name in existing_data and deck_name in metadata:
                existing_deck = existing_data[deck_name]
                new_deck = metadata[deck_name]
                
                # Preserve enriched fields if deck is still active and metadata matches
                if (existing_deck.get('active', False) and 
                    new_deck.get('active', False) and
                    existing_deck.get('title') == new_deck.get('title') and
                    existing_deck.get('artist') == new_deck.get('artist')):
                    # Keep enriched fields from existing data
                    for field in ['lastfm_tags', 'refined_keywords', 'keyword_scores', 
                                 'key_characteristics', 'gifs', 'current_enriched', 'next_enriched']:
                        if field in existing_deck:
                            new_deck[field] = existing_deck[field]
                    # Preserve transition state for the same active track
                    if 'transition' in existing_deck:
                        new_deck['transition'] = existing_deck['transition']

        # If neither deck is marked active, keep previous active_deck to avoid flapping
        if (not metadata.get('deck1', {}).get('active') and
            not metadata.get('deck2', {}).get('active') and
            'active_deck' in existing_data):
            metadata['active_deck'] = existing_data.get('active_deck', metadata.get('active_deck'))
        
        # Add timestamp
        metadata["timestamp"] = datetime.now().isoformat()
        metadata["last_updated"] = time.time()
        
        # Write to file atomically (write to temp file, then rename)
        temp_file = f"{output_file}.tmp"
        with open(temp_file, 'w') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        # Atomic rename (works on Unix-like systems)
        Path(temp_file).rename(output_file)
        
        logger.debug(f"Metadata saved to {output_file} (preserved enriched data)")
        
    except Exception as e:
        logger.error(f"Failed to save metadata to JSON: {e}", exc_info=True)


def main():
    """Main loop that continuously captures and updates metadata."""
    global RUNNING
    
    # Register signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("DjCap starting...")
    logger.info(f"Update interval: {UPDATE_INTERVAL} seconds")
    logger.info(f"Output file: {OUTPUT_FILE}")
    logger.info("Press Ctrl+C to stop")
    
    consecutive_errors = 0
    max_consecutive_errors = 5
    
    while RUNNING:
        try:
            # Capture djay Pro window
            logger.debug("Capturing djay Pro window...")
            screenshot = capture_djay_window()
            logger.debug(f"Screenshot captured: {screenshot.size}")
            
            # Extract metadata
            logger.debug("Extracting metadata...")
            metadata = extract_metadata(screenshot)
            
            # Save to JSON
            save_metadata_to_json(metadata, OUTPUT_FILE)
            
            # Log summary
            deck1 = metadata.get("deck1", {})
            deck2 = metadata.get("deck2", {})
            logger.info(
                f"Updated - Deck1: {deck1.get('title', 'N/A')[:30]} | "
                f"Deck2: {deck2.get('title', 'N/A')[:30]}"
            )
            
            # Reset error counter on success
            consecutive_errors = 0
            
        except DjayProWindowNotFoundError as e:
            consecutive_errors += 1
            logger.warning(f"djay Pro window not found (error {consecutive_errors}/{max_consecutive_errors}): {e}")
            
            if consecutive_errors >= max_consecutive_errors:
                logger.error("Too many consecutive errors. Please ensure djay Pro is running.")
                # Still wait before next attempt
                time.sleep(UPDATE_INTERVAL)
                consecutive_errors = 0  # Reset after warning
            else:
                # Wait a bit before retrying
                time.sleep(UPDATE_INTERVAL)
            continue
            
        except Exception as e:
            consecutive_errors += 1
            logger.error(f"Error during capture/extraction (error {consecutive_errors}/{max_consecutive_errors}): {e}", exc_info=True)
            
            if consecutive_errors >= max_consecutive_errors:
                logger.error("Too many consecutive errors. Please check the logs.")
                time.sleep(UPDATE_INTERVAL)
                consecutive_errors = 0  # Reset after warning
            else:
                time.sleep(UPDATE_INTERVAL)
            continue
        
        # Wait before next update
        time.sleep(UPDATE_INTERVAL)
    
    logger.info("DjCap stopped.")


if __name__ == "__main__":
    main()

