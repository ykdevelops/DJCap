"""
Video similarity detection for AudioGiphy.

This module analyzes videos to detect visually similar content and helps
filter out duplicate or near-duplicate videos from rotations.
"""
from __future__ import annotations

import hashlib
import logging
import pickle
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
import numpy as np

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logging.warning("OpenCV not available for video analysis")

logger = logging.getLogger(__name__)

# Path to similarity cache
SIMILARITY_CACHE_PATH = Path(__file__).parent.parent / "data" / "output" / "video_similarity_cache.pkl"

# Similarity threshold (0.0 = identical, 1.0 = completely different)
# Videos with similarity below this threshold are considered duplicates
SIMILARITY_THRESHOLD = 0.15  # 15% difference threshold

# Number of frames to extract from each video for comparison
FRAMES_TO_EXTRACT = 3  # Start, middle, end


def _extract_video_frames(video_path: Path, num_frames: int = FRAMES_TO_EXTRACT) -> Optional[List[np.ndarray]]:
    """
    Extract frames from a video for analysis.
    
    Args:
        video_path: Path to video file
        num_frames: Number of frames to extract
        
    Returns:
        List of frame arrays (BGR format) or None if extraction fails
    """
    if not CV2_AVAILABLE:
        return None
    
    if not video_path.exists():
        logger.warning(f"Video file not found: {video_path}")
        return None
    
    try:
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            logger.warning(f"Could not open video: {video_path}")
            return None
        
        # Get video properties
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        duration = total_frames / fps if fps > 0 else 0
        
        if total_frames == 0:
            logger.warning(f"Video has no frames: {video_path}")
            cap.release()
            return None
        
        # Calculate frame indices to extract (start, middle, end)
        frame_indices = []
        if num_frames == 1:
            frame_indices = [0]
        elif num_frames == 2:
            frame_indices = [0, total_frames // 2]
        else:
            # Extract start, middle, and end frames
            frame_indices = [
                0,
                total_frames // 2,
                max(0, total_frames - 1)
            ]
        
        frames = []
        for idx in frame_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if ret:
                frames.append(frame)
        
        cap.release()
        
        if len(frames) == 0:
            logger.warning(f"No frames extracted from: {video_path}")
            return None
        
        logger.debug(f"Extracted {len(frames)} frames from {video_path.name}")
        return frames
        
    except Exception as e:
        logger.error(f"Error extracting frames from {video_path}: {e}", exc_info=True)
        return None


def _calculate_frame_signature(frame: np.ndarray) -> np.ndarray:
    """
    Calculate a signature/hash for a frame using histogram comparison.
    Uses histogram of colors as a lightweight signature.
    
    Args:
        frame: Frame array (BGR format)
        
    Returns:
        Normalized histogram signature
    """
    if not CV2_AVAILABLE:
        return None
    
    try:
        # Convert to HSV for better color analysis
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        
        # Calculate histogram (using H and S channels, ignoring V for brightness)
        hist_h = cv2.calcHist([hsv], [0], None, [50], [0, 180])
        hist_s = cv2.calcHist([hsv], [1], None, [50], [0, 256])
        
        # Normalize histograms
        cv2.normalize(hist_h, hist_h, 0, 1, cv2.NORM_MINMAX)
        cv2.normalize(hist_s, hist_s, 0, 1, cv2.NORM_MINMAX)
        
        # Combine histograms into signature
        signature = np.concatenate([hist_h.flatten(), hist_s.flatten()])
        return signature
        
    except Exception as e:
        logger.error(f"Error calculating frame signature: {e}", exc_info=True)
        return None


def _compare_video_signatures(sig1: List[np.ndarray], sig2: List[np.ndarray]) -> float:
    """
    Compare two video signatures and return similarity score.
    
    Args:
        sig1: List of frame signatures from video 1
        sig2: List of frame signatures from video 2
        
    Returns:
        Similarity score (0.0 = identical, 1.0 = completely different)
    """
    if not CV2_AVAILABLE:
        return 1.0
    
    if not sig1 or not sig2:
        return 1.0  # Different if we can't compare
    
    try:
        # Compare each frame pair and take average
        similarities = []
        min_frames = min(len(sig1), len(sig2))
        
        for i in range(min_frames):
            if sig1[i] is None or sig2[i] is None:
                continue
            
            try:
                # Use correlation coefficient for histogram comparison
                correlation = cv2.compareHist(sig1[i], sig2[i], cv2.HISTCMP_CORREL)
                # Convert correlation (1.0 = identical, 0.0 = different) to difference score
                difference = 1.0 - correlation
                similarities.append(difference)
            except Exception as e:
                logger.debug(f"Error comparing frame {i}: {e}")
                continue
        
        if not similarities:
            return 1.0
        
        # Return average difference
        return float(np.mean(similarities))
        
    except Exception as e:
        logger.error(f"Error comparing signatures: {e}", exc_info=True)
        return 1.0


def analyze_video_similarities(video_paths: List[Path]) -> Dict[str, List[Tuple[str, float]]]:
    """
    Analyze videos and detect which ones are visually similar.
    
    Args:
        video_paths: List of video file paths to analyze
        
    Returns:
        Dictionary mapping video IDs to list of similar video IDs with similarity scores
    """
    if not CV2_AVAILABLE:
        logger.warning("OpenCV not available, cannot analyze video similarities")
        return {}
    
    logger.info(f"Analyzing {len(video_paths)} videos for similarities...")
    
    # Extract signatures for all videos
    video_signatures: Dict[str, List[np.ndarray]] = {}
    
    for video_path in video_paths:
        video_id = video_path.stem
        frames = _extract_video_frames(video_path)
        if frames:
            signatures = [_f for f in frames if (_f := _calculate_frame_signature(f)) is not None]
            if signatures:
                video_signatures[video_id] = signatures
                logger.debug(f"Processed {video_id}: {len(signatures)} signatures")
    
    logger.info(f"Extracted signatures from {len(video_signatures)} videos")
    
    # Compare all video pairs
    similarities: Dict[str, List[Tuple[str, float]]] = {}
    video_ids = list(video_signatures.keys())
    
    for i, vid1_id in enumerate(video_ids):
        similar = []
        sig1 = video_signatures[vid1_id]
        
        for vid2_id in video_ids[i+1:]:
            sig2 = video_signatures.get(vid2_id)
            if not sig2:
                continue
            
            similarity_score = _compare_video_signatures(sig1, sig2)
            
            # If similar (below threshold), add to both videos' similarity lists
            if similarity_score < SIMILARITY_THRESHOLD:
                similar.append((vid2_id, similarity_score))
                # Also add reverse relationship
                if vid2_id not in similarities:
                    similarities[vid2_id] = []
                similarities[vid2_id].append((vid1_id, similarity_score))
        
        if similar:
            similarities[vid1_id] = similar
    
    logger.info(f"Found {len(similarities)} videos with similar content")
    return similarities


def load_similarity_cache() -> Dict[str, List[Tuple[str, float]]]:
    """Load similarity cache from disk."""
    if not SIMILARITY_CACHE_PATH.exists():
        return {}
    
    try:
        with open(SIMILARITY_CACHE_PATH, 'rb') as f:
            return pickle.load(f)
    except Exception as e:
        logger.warning(f"Error loading similarity cache: {e}")
        return {}


def save_similarity_cache(similarities: Dict[str, List[Tuple[str, float]]]) -> None:
    """Save similarity cache to disk."""
    try:
        SIMILARITY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SIMILARITY_CACHE_PATH, 'wb') as f:
            pickle.dump(similarities, f)
        logger.info(f"Saved similarity cache to {SIMILARITY_CACHE_PATH}")
    except Exception as e:
        logger.error(f"Error saving similarity cache: {e}", exc_info=True)


def get_similar_video_ids(video_id: str, similarity_cache: Optional[Dict[str, List[Tuple[str, float]]]] = None) -> Set[str]:
    """
    Get set of video IDs that are similar to the given video.
    
    Args:
        video_id: ID of the video (filename stem)
        similarity_cache: Optional pre-loaded similarity cache
        
    Returns:
        Set of similar video IDs
    """
    if similarity_cache is None:
        similarity_cache = load_similarity_cache()
    
    similar_ids = set()
    if video_id in similarity_cache:
        for similar_id, _score in similarity_cache[video_id]:
            similar_ids.add(similar_id)
    
    return similar_ids


def filter_similar_videos(
    selected_videos: List[Dict[str, any]],
    similarity_cache: Optional[Dict[str, List[Tuple[str, float]]]] = None
) -> List[Dict[str, any]]:
    """
    Filter out videos that are too similar to each other from a selection.
    
    Args:
        selected_videos: List of video dicts to filter
        similarity_cache: Optional pre-loaded similarity cache
        
    Returns:
        Filtered list of videos with similar ones removed
    """
    if similarity_cache is None:
        similarity_cache = load_similarity_cache()
    
    if not similarity_cache:
        # No similarity data, return as-is
        return selected_videos
    
    filtered = []
    seen_video_ids = set()
    seen_similar_groups = set()
    
    for video in selected_videos:
        video_id = video.get('id', '').replace('dance_', '')
        if not video_id:
            # Keep videos without IDs
            filtered.append(video)
            continue
        
        # Check if we've already included a similar video
        similar_ids = get_similar_video_ids(video_id, similarity_cache)
        
        # Create a similarity group key (sorted IDs of similar videos)
        group_key = tuple(sorted([video_id] + list(similar_ids)))
        
        if group_key in seen_similar_groups:
            # Skip - we've already included a video from this similarity group
            logger.debug(f"Skipping {video_id} - similar video already selected")
            continue
        
        # Add this video and mark its similarity group as seen
        filtered.append(video)
        seen_video_ids.add(video_id)
        seen_similar_groups.add(group_key)
    
    logger.info(f"Filtered {len(selected_videos)} videos to {len(filtered)} after removing similar ones")
    return filtered


__all__ = [
    'analyze_video_similarities',
    'load_similarity_cache',
    'save_similarity_cache',
    'get_similar_video_ids',
    'filter_similar_videos',
    'SIMILARITY_THRESHOLD',
]

