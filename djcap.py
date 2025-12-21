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
import os
from datetime import datetime
from pathlib import Path

# #region agent log
DEBUG_LOG_PATH = Path(__file__).parent / ".cursor" / "debug.log"
def _debug_log(location, message, data, hypothesis_id):
    try:
        DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_LOG_PATH, 'a') as f:
            log_entry = {
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": hypothesis_id,
                "location": location,
                "message": message,
                "data": data,
                "timestamp": int(time.time() * 1000)
            }
            f.write(json.dumps(log_entry) + "\n")
    except: pass
# #endregion

# Check for required dependencies before importing
# #region agent log
try:
    _debug_log("djcap.py:import_check", "Checking dependencies", {}, "A")
except:
    pass  # Debug logging may fail if directory doesn't exist yet
# #endregion

missing_deps = []
try:
    import PIL
    # #region agent log
    _debug_log("djcap.py:import_check", "PIL/Pillow available", {}, "A")
    # #endregion
except ImportError:
    missing_deps.append("Pillow")
    # #region agent log
    _debug_log("djcap.py:import_check", "PIL/Pillow missing", {}, "A")
    # #endregion

try:
    import mss
    # #region agent log
    _debug_log("djcap.py:import_check", "mss available", {}, "A")
    # #endregion
except ImportError:
    missing_deps.append("mss")
    # #region agent log
    _debug_log("djcap.py:import_check", "mss missing", {}, "A")
    # #endregion

try:
    import cv2
    # #region agent log
    _debug_log("djcap.py:import_check", "cv2 available", {}, "A")
    # #endregion
except ImportError:
    missing_deps.append("opencv-python")
    # #region agent log
    _debug_log("djcap.py:import_check", "cv2 missing", {}, "A")
    # #endregion

try:
    import numpy
    # #region agent log
    _debug_log("djcap.py:import_check", "numpy available", {}, "A")
    # #endregion
except ImportError:
    missing_deps.append("numpy")
    # #region agent log
    _debug_log("djcap.py:import_check", "numpy missing", {}, "A")
    # #endregion

if missing_deps:
    # #region agent log
    _debug_log("djcap.py:import_check", "Missing dependencies detected", {"missing": missing_deps}, "A")
    # #endregion
    print("=" * 60)
    print("ERROR: Missing required dependencies!")
    print("=" * 60)
    print(f"Missing: {', '.join(missing_deps)}")
    print("\nTo install dependencies, run:")
    print(f"  pip3 install {' '.join(missing_deps)}")
    print("\nOr install all dependencies from requirements.txt:")
    print("  pip3 install -r requirements.txt")
    print("=" * 60)
    sys.exit(1)

# Now import the modules (they should work)
try:
    from src.window_capture import capture_djay_window, DjayProWindowNotFoundError
    # #region agent log
    _debug_log("djcap.py:import", "Import window_capture", {"success": True}, "A")
    # #endregion
except Exception as e:
    # #region agent log
    _debug_log("djcap.py:import", "Import window_capture failed", {"error": str(e), "type": type(e).__name__}, "A")
    # #endregion
    raise

try:
    from src.metadata_extractor import extract_metadata
    # #region agent log
    _debug_log("djcap.py:import", "Import metadata_extractor", {"success": True}, "B")
    # #endregion
except Exception as e:
    # #region agent log
    _debug_log("djcap.py:import", "Import metadata_extractor failed", {"error": str(e), "type": type(e).__name__}, "B")
    # #endregion
    raise

try:
    from src.output_cleanup import cleanup_output_folder
    # #region agent log
    _debug_log("djcap.py:import", "Import output_cleanup", {"success": True}, "C")
    # #endregion
except Exception as e:
    # #region agent log
    _debug_log("djcap.py:import", "Import output_cleanup failed", {"error": str(e), "type": type(e).__name__}, "C")
    # #endregion
    raise

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

# Cleanup configuration
CLEANUP_CHECK_INTERVAL = 100  # Check every N writes
OUTPUT_FOLDER = "data/output"


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
    # #region agent log
    _debug_log("djcap.py:save_metadata_to_json", "Function entry", {"output_file": output_file, "has_deck1": "deck1" in metadata, "has_deck2": "deck2" in metadata}, "G")
    # #endregion
    try:
        # Preserve existing enriched data if file exists
        existing_data = {}
        file_exists = Path(output_file).exists()
        # #region agent log
        _debug_log("djcap.py:save_metadata_to_json", "File existence check", {"file_exists": file_exists}, "G")
        # #endregion
        if file_exists:
            try:
                with open(output_file, 'r') as f:
                    existing_content = f.read().strip()
                    if existing_content:
                        existing_data = json.loads(existing_content)
                        # #region agent log
                        _debug_log("djcap.py:save_metadata_to_json", "Loaded existing data", {"content_length": len(existing_content), "has_deck1": "deck1" in existing_data, "has_deck2": "deck2" in existing_data}, "G")
                        # #endregion
            except (json.JSONDecodeError, FileNotFoundError) as e:
                # #region agent log
                _debug_log("djcap.py:save_metadata_to_json", "Failed to load existing data", {"error": str(e), "error_type": type(e).__name__}, "G")
                # #endregion
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
                                 'key_characteristics', 'gifs', 'current_enriched', 'next_enriched',
                                 'gif_pool',
                                 'giphy_query', 'giphy_query_parts',
                                 'lyrics_raw', 'lyrics_synced', 'lyrics_source', 'lyrics_track_started_at',
                                 'lyrics_keywords']:
                        if field in existing_deck:
                            new_deck[field] = existing_deck[field]
                    # Preserve transition state for the same active track
                    if 'transition' in existing_deck:
                        new_deck['transition'] = existing_deck['transition']
        
        # Add timestamp
        metadata["timestamp"] = datetime.now().isoformat()
        metadata["last_updated"] = time.time()
        
        # Write to file atomically (write to temp file, then rename)
        temp_file = f"{output_file}.tmp"
        with open(temp_file, 'w') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        # Atomic rename (works on Unix-like systems)
        Path(temp_file).rename(output_file)
        
        # #region agent log
        _debug_log("djcap.py:save_metadata_to_json", "File write complete", {"temp_file": temp_file, "output_file": output_file}, "G")
        # #endregion
        logger.debug(f"Metadata saved to {output_file} (preserved enriched data)")
        
    except Exception as e:
        # #region agent log
        _debug_log("djcap.py:save_metadata_to_json", "Exception in save", {"error": str(e), "error_type": type(e).__name__}, "G")
        # #endregion
        logger.error(f"Failed to save metadata to JSON: {e}", exc_info=True)


def main():
    """Main loop that continuously captures and updates metadata."""
    global RUNNING
    
    # #region agent log
    _debug_log("djcap.py:main", "Main function entry", {"UPDATE_INTERVAL": UPDATE_INTERVAL, "OUTPUT_FILE": OUTPUT_FILE}, "D")
    # #endregion
    
    # Register signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("DjCap starting...")
    logger.info(f"Update interval: {UPDATE_INTERVAL} seconds")
    logger.info(f"Output file: {OUTPUT_FILE}")
    logger.info("Press Ctrl+C to stop")
    
    consecutive_errors = 0
    max_consecutive_errors = 5
    write_count = 0
    loop_iteration = 0
    
    while RUNNING:
        loop_iteration += 1
        # #region agent log
        _debug_log("djcap.py:main:loop", "Loop iteration start", {"iteration": loop_iteration, "consecutive_errors": consecutive_errors, "write_count": write_count}, "D")
        # #endregion
        try:
            # Capture djay Pro window
            logger.debug("Capturing djay Pro window...")
            # #region agent log
            _debug_log("djcap.py:main:capture", "Before capture_djay_window", {}, "E")
            # #endregion
            screenshot = capture_djay_window()
            # #region agent log
            _debug_log("djcap.py:main:capture", "After capture_djay_window", {"screenshot_size": str(screenshot.size) if screenshot else None, "screenshot_type": type(screenshot).__name__}, "E")
            # #endregion
            logger.debug(f"Screenshot captured: {screenshot.size}")
            
            # Extract metadata
            logger.debug("Extracting metadata...")
            # #region agent log
            _debug_log("djcap.py:main:extract", "Before extract_metadata", {}, "F")
            # #endregion
            metadata = extract_metadata(screenshot)
            # #region agent log
            _debug_log("djcap.py:main:extract", "After extract_metadata", {"has_deck1": "deck1" in metadata, "has_deck2": "deck2" in metadata, "deck1_title": metadata.get("deck1", {}).get("title"), "deck2_title": metadata.get("deck2", {}).get("title")}, "F")
            # #endregion
            
            # Save to JSON
            # #region agent log
            _debug_log("djcap.py:main:save", "Before save_metadata_to_json", {"output_file": OUTPUT_FILE}, "G")
            # #endregion
            save_metadata_to_json(metadata, OUTPUT_FILE)
            # #region agent log
            _debug_log("djcap.py:main:save", "After save_metadata_to_json", {"write_count": write_count + 1}, "G")
            # #endregion
            write_count += 1
            
            # Periodic cleanup check
            if write_count % CLEANUP_CHECK_INTERVAL == 0:
                try:
                    cleanup_output_folder(OUTPUT_FOLDER)
                except Exception as e:
                    logger.warning(f"Cleanup error (non-fatal): {e}")
            
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
            # #region agent log
            _debug_log("djcap.py:main:error", "DjayProWindowNotFoundError", {"error": str(e), "consecutive_errors": consecutive_errors, "max_errors": max_consecutive_errors}, "E")
            # #endregion
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
            # #region agent log
            _debug_log("djcap.py:main:error", "General exception", {"error": str(e), "error_type": type(e).__name__, "consecutive_errors": consecutive_errors, "max_errors": max_consecutive_errors}, "H")
            # #endregion
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

