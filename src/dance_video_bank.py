"""
Dance video bank support for AudioGiphy.

This module provides functions to retrieve random videos from the offline
dance_mp4_bank folder for use in the media rotation.
"""
from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# Path to the dance video bank
DANCE_VIDEO_BANK_PATH = Path(__file__).parent.parent / "data" / "dance_mp4_bank"

_VIDEO_LIST_CACHE = None


def _get_video_list() -> List[Path]:
    """Get list of all MP4 files in the dance video bank."""
    global _VIDEO_LIST_CACHE
    
    if _VIDEO_LIST_CACHE is not None:
        return _VIDEO_LIST_CACHE
    
    if not DANCE_VIDEO_BANK_PATH.exists():
        logger.warning(f"Dance video bank not found at {DANCE_VIDEO_BANK_PATH}")
        _VIDEO_LIST_CACHE = []
        return []
    
    videos = list(DANCE_VIDEO_BANK_PATH.glob("*.mp4"))
    _VIDEO_LIST_CACHE = videos
    logger.info(f"Found {len(videos)} videos in dance video bank")
    return videos


def get_dance_videos(count: int = 5) -> List[Dict[str, Any]]:
    """
    Return random videos from the dance video bank.
    
    Args:
        count: Number of videos to return
        
    Returns:
        List of video dicts with id, url, title, mime, etc.
    """
    videos = _get_video_list()
    
    if not videos:
        logger.warning("No videos available in dance video bank")
        return []
    
    if len(videos) < count:
        logger.warning(f"Only {len(videos)} videos available, requested {count}")
        selected = videos
    else:
        selected = random.sample(videos, count)
    
    result = []
    for video_path in selected:
        # Create a video dict similar to GIF structure
        video_dict = {
            "id": f"dance_{video_path.stem}",
            "url": f"/api/dance_video/{video_path.name}",
            "title": f"Dance Video {video_path.stem}",
            "mime": "video/mp4",
            "source": "dance_mp4_bank",
            "width": 480,  # Default, could be enhanced with actual video metadata
            "height": 270,
            "tags": ["dance", "offline"]
        }
        result.append(video_dict)
    
    logger.info(f"Selected {len(result)} videos from dance video bank")
    return result


__all__ = ["get_dance_videos"]

