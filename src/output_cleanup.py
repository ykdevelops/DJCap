#!/usr/bin/env python3
"""
Output folder cleanup module.
Automatically cleans the output folder when it grows too large.
"""
import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Configuration constants
CLEANUP_FOLDER_SIZE_THRESHOLD = 500 * 1024 * 1024  # 500MB
CLEANUP_JSON_SIZE_THRESHOLD = 50 * 1024 * 1024  # 50MB
CLEANUP_LOG_SIZE_THRESHOLD = 10 * 1024 * 1024  # 10MB
CLEANUP_STATE_SIZE_THRESHOLD = 5 * 1024 * 1024  # 5MB


def get_folder_size(folder_path: str) -> int:
    """Calculate total size of all files in a folder."""
    total_size = 0
    try:
        for dirpath, dirnames, filenames in os.walk(folder_path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                try:
                    total_size += os.path.getsize(filepath)
                except (OSError, FileNotFoundError):
                    pass
    except Exception as e:
        logger.warning(f"Error calculating folder size: {e}")
    return total_size


def get_file_size(file_path: str) -> int:
    """Get file size in bytes."""
    try:
        return os.path.getsize(file_path)
    except (OSError, FileNotFoundError):
        return 0


def sanitize_deck_data(deck_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize deck data by removing recursive structures and keeping only essential fields.
    
    Args:
        deck_data: Dictionary with deck metadata (may contain recursive current_enriched)
        
    Returns:
        Cleaned deck data with only top-level fields
    """
    # Define fields to keep at top level
    basic_fields = ['deck', 'title', 'artist', 'bpm', 'key', 'active']
    enriched_fields = [
        'lastfm_tags', 'refined_keywords', 'keyword_scores', 'key_characteristics',
        'gifs', 'gif_pool', 'giphy_query', 'giphy_query_parts',
        'lyrics_raw', 'lyrics_synced', 'lyrics_source', 'lyrics_track_started_at',
        'lyrics_keywords', 'transition'
    ]
    
    cleaned = {}
    
    # Copy basic fields
    for field in basic_fields:
        if field in deck_data:
            cleaned[field] = deck_data[field]
    
    # Copy enriched fields (but not nested current_enriched or next_enriched)
    for field in enriched_fields:
        if field in deck_data:
            cleaned[field] = deck_data[field]
    
    # Handle current_enriched and next_enriched separately
    # Extract their content but don't nest them recursively
    if 'current_enriched' in deck_data:
        current = deck_data['current_enriched']
        # If current_enriched itself has a current_enriched, extract the inner one
        if isinstance(current, dict) and 'current_enriched' in current:
            # Recursive structure detected - extract the innermost
            inner = current
            depth = 0
            while isinstance(inner, dict) and 'current_enriched' in inner:
                inner = inner['current_enriched']
                depth += 1
                if depth > 100:  # Safety limit
                    logger.warning("Deep recursion detected in current_enriched, breaking")
                    break
            # Use the innermost as the source
            current = inner
        
        # Merge current_enriched fields into top level (but don't keep current_enriched itself)
        if isinstance(current, dict):
            for field in basic_fields + enriched_fields:
                if field in current and field not in cleaned:
                    cleaned[field] = current[field]
    
    # Same for next_enriched
    if 'next_enriched' in deck_data:
        next_enriched = deck_data['next_enriched']
        if isinstance(next_enriched, dict) and 'current_enriched' in next_enriched:
            # Extract innermost
            inner = next_enriched
            depth = 0
            while isinstance(inner, dict) and 'current_enriched' in inner:
                inner = inner['current_enriched']
                depth += 1
                if depth > 100:
                    logger.warning("Deep recursion detected in next_enriched, breaking")
                    break
            next_enriched = inner
        
        # Only keep next_enriched if it's different from current data
        if isinstance(next_enriched, dict):
            cleaned['next_enriched'] = {
                'title': next_enriched.get('title'),
                'artist': next_enriched.get('artist'),
                'gifs': next_enriched.get('gifs', [])[:5],  # Limit to 5 GIFs
                'refined_keywords': next_enriched.get('refined_keywords', [])[:10]  # Limit keywords
            }
    
    return cleaned


def cleanup_djcap_json(json_file: str) -> bool:
    """
    Clean up djcap_output.json by extracting only the latest state.
    
    Args:
        json_file: Path to djcap_output.json
        
    Returns:
        True if cleanup was performed, False otherwise
    """
    try:
        # Read current file
        with open(json_file, 'r') as f:
            data = json.load(f)
        
        # Extract only essential top-level fields
        cleaned_data = {
            'deck1': sanitize_deck_data(data.get('deck1', {})),
            'deck2': sanitize_deck_data(data.get('deck2', {})),
            'active_deck': data.get('active_deck', 'deck1'),
            'timestamp': data.get('timestamp'),
            'last_updated': data.get('last_updated')
        }
        
        # Write cleaned data atomically
        temp_file = f"{json_file}.tmp"
        with open(temp_file, 'w') as f:
            json.dump(cleaned_data, f, indent=2, ensure_ascii=False)
        
        # Atomic rename
        Path(temp_file).rename(json_file)
        
        old_size = get_file_size(json_file)
        new_size = get_file_size(json_file)
        logger.info(f"Cleaned djcap_output.json: {old_size / (1024*1024):.1f}MB -> {new_size / (1024*1024):.1f}MB")
        return True
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error in {json_file}: {e}. File may be corrupted.")
        # Try to create a minimal valid file
        try:
            minimal_data = {
                'deck1': {'deck': 'deck1', 'title': None, 'artist': None, 'bpm': None, 'key': None, 'active': False},
                'deck2': {'deck': 'deck2', 'title': None, 'artist': None, 'bpm': None, 'key': None, 'active': False},
                'active_deck': 'deck1',
                'timestamp': None,
                'last_updated': None
            }
            temp_file = f"{json_file}.tmp"
            with open(temp_file, 'w') as f:
                json.dump(minimal_data, f, indent=2, ensure_ascii=False)
            Path(temp_file).rename(json_file)
            logger.info(f"Created minimal valid JSON file after corruption")
            return True
        except Exception as e2:
            logger.error(f"Failed to create minimal JSON file: {e2}")
            return False
    except Exception as e:
        logger.error(f"Error cleaning djcap_output.json: {e}", exc_info=True)
        return False


def cleanup_output_folder(output_folder: str, force_json_cleanup: bool = False) -> Dict[str, Any]:
    """
    Clean up the output folder based on size thresholds.
    
    Args:
        output_folder: Path to the output folder
        force_json_cleanup: If True, clean JSON even if under threshold
        
    Returns:
        Dictionary with cleanup statistics
    """
    stats = {
        'folder_cleaned': False,
        'json_cleaned': False,
        'logs_deleted': 0,
        'state_files_warned': 0,
        'total_size_before': 0,
        'total_size_after': 0
    }
    
    if not os.path.exists(output_folder):
        logger.warning(f"Output folder does not exist: {output_folder}")
        return stats
    
    # Calculate folder size
    total_size = get_folder_size(output_folder)
    stats['total_size_before'] = total_size
    
    logger.debug(f"Output folder size: {total_size / (1024*1024):.1f}MB")
    
    # Check if folder exceeds threshold
    folder_needs_cleanup = total_size > CLEANUP_FOLDER_SIZE_THRESHOLD
    
    # Process each file
    for filename in os.listdir(output_folder):
        file_path = os.path.join(output_folder, filename)
        
        if not os.path.isfile(file_path):
            continue
        
        # Never delete PID files
        if filename.endswith('.pid'):
            continue
        
        file_size = get_file_size(file_path)
        
        # Handle djcap_output.json
        if filename == 'djcap_output.json':
            if file_size > CLEANUP_JSON_SIZE_THRESHOLD or force_json_cleanup or folder_needs_cleanup:
                logger.info(f"Cleaning {filename} (size: {file_size / (1024*1024):.1f}MB)")
                if cleanup_djcap_json(file_path):
                    stats['json_cleaned'] = True
        
        # Handle log files
        elif filename.endswith('.log'):
            if file_size > CLEANUP_LOG_SIZE_THRESHOLD or folder_needs_cleanup:
                try:
                    os.remove(file_path)
                    logger.info(f"Deleted log file: {filename} (size: {file_size / (1024*1024):.1f}MB)")
                    stats['logs_deleted'] += 1
                except Exception as e:
                    logger.error(f"Error deleting log file {filename}: {e}")
        
        # Handle state files (giphy_history.json, giphy_rate_state.json)
        elif filename.endswith('.json') and filename != 'djcap_output.json':
            if file_size > CLEANUP_STATE_SIZE_THRESHOLD:
                logger.warning(f"State file {filename} is large ({file_size / (1024*1024):.1f}MB) but keeping it")
                stats['state_files_warned'] += 1
        
        # Handle temporary files
        elif filename.endswith('.tmp'):
            try:
                os.remove(file_path)
                logger.info(f"Deleted temporary file: {filename}")
            except Exception as e:
                logger.error(f"Error deleting temp file {filename}: {e}")
    
    # Calculate final folder size
    stats['total_size_after'] = get_folder_size(output_folder)
    
    if stats['json_cleaned'] or stats['logs_deleted'] > 0:
        stats['folder_cleaned'] = True
        logger.info(
            f"Cleanup complete: JSON cleaned={stats['json_cleaned']}, "
            f"logs deleted={stats['logs_deleted']}, "
            f"size: {stats['total_size_before'] / (1024*1024):.1f}MB -> {stats['total_size_after'] / (1024*1024):.1f}MB"
        )
    
    return stats

