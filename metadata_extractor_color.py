"""
Color-based text region detection for djay Pro.
Detects white text (title) and grey text (artist/BPM) regions.
"""
import numpy as np
import cv2
from typing import Dict, Tuple, Optional

# Color thresholds
WHITE_THRESHOLD = 200  # Minimum RGB value to be considered white
GREY_MIN = 100  # Minimum RGB value for grey
GREY_MAX = 200  # Maximum RGB value for grey


def detect_text_regions_by_color(deck_region: np.ndarray) -> Dict[str, Optional[Tuple[int, int, int, int]]]:
    """
    Detect text regions based on color: white for title, grey for artist/BPM.
    Returns bounding boxes for title, artist, and bpm regions.
    
    Args:
        deck_region: numpy array image of the deck region (RGB)
        
    Returns:
        Dictionary with 'title', 'artist', 'bpm' bounding boxes (x_start, y_start, x_end, y_end)
        or None if not detected
    """
    height, width = deck_region.shape[:2]
    
    # Ensure RGB format
    if len(deck_region.shape) == 2:
        deck_region_rgb = cv2.cvtColor(deck_region, cv2.COLOR_GRAY2RGB)
    elif deck_region.shape[2] == 4:
        deck_region_rgb = cv2.cvtColor(deck_region, cv2.COLOR_RGBA2RGB)
    else:
        deck_region_rgb = deck_region
    
    # Create masks for white and grey text
    # White text: all RGB channels > WHITE_THRESHOLD
    white_mask = np.all(deck_region_rgb > WHITE_THRESHOLD, axis=2)
    
    # Grey text: RGB values between GREY_MIN and GREY_MAX, and channels are similar
    grey_condition = np.all((deck_region_rgb >= GREY_MIN) & (deck_region_rgb <= GREY_MAX), axis=2)
    channel_diff = np.max(deck_region_rgb, axis=2) - np.min(deck_region_rgb, axis=2)
    grey_mask = grey_condition & (channel_diff < 30)  # Channels should be similar for grey
    
    # Find connected components for white text (title)
    white_components = cv2.connectedComponentsWithStats(
        white_mask.astype(np.uint8) * 255, connectivity=8
    )
    num_labels, labels, stats, centroids = white_components
    
    # Find the largest white text region (likely the title)
    title_bbox = None
    if num_labels > 1:
        # Skip background (label 0)
        white_areas = stats[1:, cv2.CC_STAT_AREA]
        if len(white_areas) > 0:
            largest_idx = np.argmax(white_areas) + 1
            x = stats[largest_idx, cv2.CC_STAT_LEFT]
            y = stats[largest_idx, cv2.CC_STAT_TOP]
            w = stats[largest_idx, cv2.CC_STAT_WIDTH]
            h = stats[largest_idx, cv2.CC_STAT_HEIGHT]
            title_bbox = (x, y, x + w, y + h)
    
    # Find connected components for grey text (artist and BPM)
    grey_components = cv2.connectedComponentsWithStats(
        grey_mask.astype(np.uint8) * 255, connectivity=8
    )
    num_labels_grey, labels_grey, stats_grey, centroids_grey = grey_components
    
    artist_bbox = None
    bpm_bbox = None
    
    if num_labels_grey > 1:
        # Get all grey text regions, sorted by x position (left to right)
        grey_regions = []
        for i in range(1, num_labels_grey):
            x = stats_grey[i, cv2.CC_STAT_LEFT]
            y = stats_grey[i, cv2.CC_STAT_TOP]
            w = stats_grey[i, cv2.CC_STAT_WIDTH]
            h = stats_grey[i, cv2.CC_STAT_HEIGHT]
            area = stats_grey[i, cv2.CC_STAT_AREA]
            # Filter out very small regions (noise)
            if area > 50:  # Minimum area threshold
                grey_regions.append((x, y, x + w, y + h, area))
        
        # Sort by x position (left to right)
        grey_regions.sort(key=lambda r: r[0])
        
        # First grey region is likely artist, second is likely BPM
        # They should be on similar y-level (same line)
        if len(grey_regions) >= 1:
            artist_bbox = grey_regions[0][:4]
            
        if len(grey_regions) >= 2:
            # Check if second region is BPM (usually to the right of artist)
            first_y = grey_regions[0][1]
            second_y = grey_regions[1][1]
            # They should be on similar horizontal line
            if abs(first_y - second_y) < 20:  # On similar horizontal line
                bpm_bbox = grey_regions[1][:4]
    
    return {
        'title': title_bbox,
        'artist': artist_bbox,
        'bpm': bpm_bbox
    }

