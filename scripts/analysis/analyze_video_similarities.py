#!/usr/bin/env python3
"""
Script to analyze video similarities in the dance video bank.

This script extracts frames from videos and compares them to detect
visually similar content. Results are cached for faster lookups.
"""
import sys
from pathlib import Path

# Add project root to path (two levels up from scripts/analysis/)
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.video_similarity import analyze_video_similarities, save_similarity_cache, load_similarity_cache
from src.dance_video_bank import DANCE_VIDEO_BANK_PATH
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Analyze all videos in the dance video bank for similarities."""
    if not DANCE_VIDEO_BANK_PATH.exists():
        logger.error(f"Dance video bank not found at {DANCE_VIDEO_BANK_PATH}")
        return
    
    # Get all video files
    video_paths = list(DANCE_VIDEO_BANK_PATH.glob("*.mp4"))
    
    if not video_paths:
        logger.warning("No video files found in dance video bank")
        return
    
    logger.info(f"Found {len(video_paths)} videos to analyze")
    
    # Load existing cache to see what we already know
    existing_cache = load_similarity_cache()
    logger.info(f"Loaded {len(existing_cache)} existing similarity entries")
    
    # Analyze all videos
    similarities = analyze_video_similarities(video_paths)
    
    # Save cache
    save_similarity_cache(similarities)
    
    # Print summary
    total_similar_pairs = sum(len(sims) for sims in similarities.values())
    logger.info(f"Analysis complete:")
    logger.info(f"  - Videos analyzed: {len(video_paths)}")
    logger.info(f"  - Videos with similar content: {len(similarities)}")
    logger.info(f"  - Total similar pairs: {total_similar_pairs // 2}")  # Divide by 2 since each pair is counted twice
    
    # Print some examples
    if similarities:
        logger.info("\nSimilar video pairs found:")
        shown = set()
        for vid_id, similar_list in list(similarities.items())[:10]:  # Show first 10
            for similar_id, score in similar_list:
                pair = tuple(sorted([vid_id, similar_id]))
                if pair not in shown:
                    logger.info(f"  - {vid_id} <-> {similar_id} (similarity: {score:.3f})")
                    shown.add(pair)


if __name__ == "__main__":
    main()


