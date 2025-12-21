"""
Video trimming module to detect and remove repeated segments within videos.

Detects loops/repetitions in video files and trims to keep only the first unique segment.
"""
from __future__ import annotations

import hashlib
import logging
import pickle
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import numpy as np

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logging.warning("OpenCV not available for video trimming")

logger = logging.getLogger(__name__)

# Path to trimming cache (stores trim points for videos)
TRIMMING_CACHE_PATH = Path(__file__).parent.parent / "data" / "output" / "video_trimming_cache.pkl"

# Similarity threshold for detecting repeated frames (lower = more strict)
FRAME_SIMILARITY_THRESHOLD = 0.05  # 5% difference threshold

# Number of frames to sample per second for analysis
FRAMES_PER_SECOND = 2  # Sample 2 frames per second

# Minimum segment length in seconds to consider (avoid trimming very short videos)
MIN_SEGMENT_LENGTH = 0.5  # 0.5 seconds


def _extract_sample_frames(video_path: Path, frames_per_second: int = FRAMES_PER_SECOND) -> Optional[Tuple[List[np.ndarray], float]]:
    """
    Extract sample frames from video for analysis.
    
    Args:
        video_path: Path to video file
        frames_per_second: Number of frames to extract per second
        
    Returns:
        Tuple of (list of frames, fps) or None if extraction fails
    """
    if not CV2_AVAILABLE:
        return None
    
    if not video_path.exists():
        return None
    
    try:
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return None
        
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0
        
        if total_frames == 0 or fps == 0:
            cap.release()
            return None
        
        # Calculate frame interval (sample every N frames)
        frame_interval = max(1, int(fps / frames_per_second))
        
        frames = []
        frame_numbers = []
        
        for frame_num in range(0, total_frames, frame_interval):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()
            if ret:
                frames.append(frame)
                frame_numbers.append(frame_num)
            else:
                break
        
        cap.release()
        
        if len(frames) == 0:
            return None
        
        return (frames, fps)
        
    except Exception as e:
        logger.error(f"Error extracting frames from {video_path}: {e}", exc_info=True)
        return None


def _calculate_frame_hash(frame: np.ndarray) -> str:
    """
    Calculate a simple hash for a frame using downscaled version for speed.
    
    Args:
        frame: Frame array (BGR format)
        
    Returns:
        Hash string of the frame
    """
    try:
        # Resize to small size for faster comparison (80x45)
        small = cv2.resize(frame, (80, 45))
        # Convert to grayscale
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        # Calculate hash of pixel values
        frame_hash = hashlib.md5(gray.tobytes()).hexdigest()
        return frame_hash
    except Exception as e:
        logger.error(f"Error calculating frame hash: {e}", exc_info=True)
        return ""


def _compare_frames_hash(frame1_hash: str, frame2_hash: str) -> bool:
    """
    Compare two frame hashes to detect if frames are similar.
    
    Args:
        frame1_hash: Hash of frame 1
        frame2_hash: Hash of frame 2
        
    Returns:
        True if frames are identical (same hash)
    """
    return frame1_hash == frame2_hash and frame1_hash != ""


def _detect_repetition_point(frames: List[np.ndarray]) -> Optional[int]:
    """
    Detect where video starts repeating by comparing frames.
    
    Uses a sliding window approach to find where the video loops back to the beginning.
    
    Args:
        frames: List of sample frames from video
        
    Returns:
        Index where repetition is detected (the original segment), or None if no repetition found
    """
    if len(frames) < 4:  # Need at least a few frames to detect repetition
        return None
    
    # Calculate hashes for all frames
    frame_hashes = []
    for frame in frames:
        frame_hash = _calculate_frame_hash(frame)
        if not frame_hash:
            return None
        frame_hashes.append(frame_hash)
    
    # Strategy: Look for a pattern where later frames match earlier frames
    # This indicates the video is looping back to the start
    
    # Start checking from mid-point onwards (videos typically loop at least once)
    start_check = len(frame_hashes) // 2
    
    for i in range(start_check, len(frame_hashes)):
        # Compare current frame with early frames to find where loop starts
        for j in range(min(5, i // 2)):  # Compare with first 5 frames or up to half-way
            if _compare_frames_hash(frame_hashes[i], frame_hashes[j]):
                # Found a match - check if next frame also matches (more confident detection)
                if i + 1 < len(frame_hashes) and j + 1 < len(frame_hashes):
                    if _compare_frames_hash(frame_hashes[i + 1], frame_hashes[j + 1]):
                        # Confirmed: sequence matches, video is repeating
                        logger.debug(f"Repetition detected: frame sequence starting at {i} matches sequence starting at {j}")
                        return j
                else:
                    # Single frame match (still likely a repetition)
                    logger.debug(f"Repetition detected: frame {i} matches frame {j}")
                    return j
    
    return None


def analyze_video_for_repetition(video_path: Path) -> Optional[float]:
    """
    Analyze a video to detect if it contains repeated segments.
    
    Args:
        video_path: Path to video file
        
    Returns:
        Duration in seconds to trim to (where repetition starts), or None if no repetition
    """
    if not CV2_AVAILABLE:
        return None
    
    result = _extract_sample_frames(video_path)
    if not result:
        return None
    
    frames, fps = result
    
    if len(frames) < 4:
        return None
    
    # Detect where repetition starts (returns index of original segment)
    repeat_index = _detect_repetition_point(frames)
    
    if repeat_index is None:
        # No repetition detected
        return None
    
    # Calculate time where repetition starts
    # We sampled frames at FRAMES_PER_SECOND intervals
    frame_interval = 1.0 / FRAMES_PER_SECOND
    
    # repeat_index points to where the loop starts, so we want to trim just before the next cycle
    # Add a small buffer to include the full segment
    trim_time = (repeat_index + 1) * frame_interval
    
    # Get actual video duration to ensure we don't trim past the end
    try:
        import cv2
        cap = cv2.VideoCapture(str(video_path))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        video_fps = cap.get(cv2.CAP_PROP_FPS)
        actual_duration = total_frames / video_fps if video_fps > 0 else None
        cap.release()
        
        if actual_duration and trim_time > actual_duration * 0.9:
            # If trim point is too close to end, probably not a real repetition
            logger.debug(f"Trim time {trim_time:.2f}s is too close to video end ({actual_duration:.2f}s), ignoring")
            return None
    except Exception:
        pass  # Continue without duration check
    
    # Ensure minimum segment length
    if trim_time < MIN_SEGMENT_LENGTH:
        logger.debug(f"Trim time {trim_time:.2f}s is too short, keeping full video")
        return None
    
    logger.info(f"Video {video_path.name}: repetition detected at {trim_time:.2f}s")
    return trim_time


def get_video_trim_info(video_path: Path, cache: Optional[Dict[str, float]] = None) -> Optional[float]:
    """
    Get trimming information for a video (loads from cache or analyzes).
    
    Args:
        video_path: Path to video file
        cache: Optional pre-loaded cache
        
    Returns:
        Duration to trim to (seconds), or None if no trimming needed
    """
    video_id = video_path.stem
    
    # Load cache if not provided
    if cache is None:
        cache = load_trimming_cache()
    
    # Check cache first
    if video_id in cache:
        trim_time = cache[video_id]
        if trim_time is None:
            return None  # Cached as "no repetition"
        return trim_time
    
    # Analyze video
    trim_time = analyze_video_for_repetition(video_path)
    
    # Save to cache
    if cache is not None:
        cache[video_id] = trim_time
        save_trimming_cache(cache)
    
    return trim_time


def load_trimming_cache() -> Dict[str, Optional[float]]:
    """Load trimming cache from disk."""
    if not TRIMMING_CACHE_PATH.exists():
        return {}
    
    try:
        with open(TRIMMING_CACHE_PATH, 'rb') as f:
            return pickle.load(f)
    except Exception as e:
        logger.warning(f"Error loading trimming cache: {e}")
        return {}


def save_trimming_cache(cache: Dict[str, Optional[float]]) -> None:
    """Save trimming cache to disk."""
    try:
        TRIMMING_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(TRIMMING_CACHE_PATH, 'wb') as f:
            pickle.dump(cache, f)
        logger.debug(f"Saved trimming cache to {TRIMMING_CACHE_PATH}")
    except Exception as e:
        logger.error(f"Error saving trimming cache: {e}", exc_info=True)


def trim_video_ffmpeg(input_path: Path, output_path: Path, duration: float) -> bool:
    """
    Trim a video using ffmpeg to specified duration.
    
    Args:
        input_path: Path to input video
        output_path: Path to output trimmed video
        duration: Duration in seconds to trim to
        
    Returns:
        True if successful, False otherwise
    """
    import subprocess
    
    try:
        # Use ffmpeg to trim video
        cmd = [
            'ffmpeg',
            '-i', str(input_path),
            '-t', str(duration),
            '-c', 'copy',  # Copy codec (fast, no re-encoding)
            '-y',  # Overwrite output file
            str(output_path)
        ]
        
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False
        )
        
        if result.returncode == 0 and output_path.exists():
            logger.info(f"Trimmed video {input_path.name} to {duration:.2f}s -> {output_path.name}")
            return True
        else:
            logger.error(f"ffmpeg failed to trim video: {result.stderr.decode()}")
            return False
            
    except FileNotFoundError:
        logger.error("ffmpeg not found. Please install ffmpeg to use video trimming.")
        return False
    except Exception as e:
        logger.error(f"Error trimming video with ffmpeg: {e}", exc_info=True)
        return False


__all__ = [
    'analyze_video_for_repetition',
    'get_video_trim_info',
    'load_trimming_cache',
    'save_trimming_cache',
    'trim_video_ffmpeg',
]

