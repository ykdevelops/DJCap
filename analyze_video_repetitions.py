#!/usr/bin/env python3
"""
Script to analyze videos for repeated segments and trim them.

This script processes all videos in the dance video bank to detect
loops/repetitions and caches trim points.
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.video_trimming import (
    analyze_video_for_repetition,
    load_trimming_cache,
    save_trimming_cache,
    trim_video_ffmpeg
)
from src.dance_video_bank import DANCE_VIDEO_BANK_PATH
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Analyze all videos in the dance video bank for repetitions."""
    if not DANCE_VIDEO_BANK_PATH.exists():
        logger.error(f"Dance video bank not found at {DANCE_VIDEO_BANK_PATH}")
        return
    
    # Get all video files
    video_paths = list(DANCE_VIDEO_BANK_PATH.glob("*.mp4"))
    
    if not video_paths:
        logger.warning("No video files found in dance video bank")
        return
    
    logger.info(f"Found {len(video_paths)} videos to analyze")
    
    # Load existing cache
    cache = load_trimming_cache()
    logger.info(f"Loaded {len(cache)} existing trim entries from cache")
    
    # Analyze videos
    videos_with_repetitions = 0
    videos_analyzed = 0
    
    for video_path in video_paths:
        video_id = video_path.stem
        
        # Skip if already in cache
        if video_id in cache:
            logger.debug(f"Skipping {video_id} - already in cache")
            continue
        
        videos_analyzed += 1
        logger.info(f"Analyzing {video_path.name} ({videos_analyzed}/{len(video_paths)})...")
        
        trim_duration = analyze_video_for_repetition(video_path)
        cache[video_id] = trim_duration
        
        if trim_duration is not None:
            videos_with_repetitions += 1
            logger.info(f"  -> Repetition detected! Trim to {trim_duration:.2f}s")
        
        # Save cache periodically (every 10 videos)
        if videos_analyzed % 10 == 0:
            save_trimming_cache(cache)
            logger.info(f"Progress saved: {videos_analyzed}/{len(video_paths)} analyzed")
    
    # Final save
    save_trimming_cache(cache)
    
    # Print summary
    logger.info(f"\nAnalysis complete:")
    logger.info(f"  - Videos analyzed: {videos_analyzed}")
    logger.info(f"  - Videos with repetitions: {videos_with_repetitions}")
    logger.info(f"  - Videos without repetitions: {videos_analyzed - videos_with_repetitions}")
    logger.info(f"  - Total videos in cache: {len(cache)}")


if __name__ == "__main__":
    main()

