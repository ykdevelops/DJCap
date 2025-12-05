"""
Metadata extraction from djay Pro screenshot using Apple Vision (ocrmac).
Extracts Deck #, Song Title, Artist Name, BPM, and Key from both decks.
"""
import re
import logging
import json
import os
from typing import Dict, Any, Optional, Tuple, List
import numpy as np
from PIL import Image
import cv2

logger = logging.getLogger(__name__)

# Region padding for OCR (expands regions to capture more context)
REGION_PADDING = 15  # pixels

# Path to region coordinates file
REGION_COORDINATES_FILE = "data/region_coordinates.json"

# Color thresholds for text detection
# White text: high brightness (RGB values close to 255)
# Grey text: medium brightness (RGB values around 128-200)
WHITE_THRESHOLD = 200  # Minimum RGB value to be considered white
GREY_MIN = 100  # Minimum RGB value for grey
GREY_MAX = 200  # Maximum RGB value for grey

def _load_region_coordinates() -> Optional[Dict]:
    """Load region coordinates from JSON file if it exists."""
    if os.path.exists(REGION_COORDINATES_FILE):
        try:
            with open(REGION_COORDINATES_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load region coordinates: {e}")
    return None

try:
    from ocrmac.ocrmac import text_from_image
    OCRMAC_AVAILABLE = True
except ImportError:
    OCRMAC_AVAILABLE = False
    logger.error("ocrmac not available. Please install it: pip install ocrmac")


def _extract_text_with_ocrmac(region_image: Image.Image, region_name: str) -> Optional[str]:
    """
    Extract text using ocrmac (Apple Vision OCR).
    
    Args:
        region_image: PIL Image of the region
        region_name: Name of the region for logging
        
    Returns:
        Extracted text string or None if extraction fails
    """
    if not OCRMAC_AVAILABLE:
        logger.warning("ocrmac not available, cannot extract text")
        return None
    
    try:
        # Use text_from_image function directly
        # detail=False returns list of strings, detail=True returns list of tuples
        results = text_from_image(region_image, recognition_level="accurate", detail=False)
        
        # results is a list of strings when detail=False
        if results:
            # Join all text strings
            text = " ".join(str(item) for item in results if item).strip()
            
            if text:
                logger.debug(f"ocrmac extracted from {region_name}: '{text}'")
                return text
            else:
                logger.debug(f"ocrmac returned empty text for {region_name}")
                return None
        else:
            logger.debug(f"ocrmac returned empty results for {region_name}")
            return None
            
    except Exception as e:
        logger.debug(f"ocrmac failed for {region_name}: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return None


def _detect_artist_bpm_split(combined_region: np.ndarray, gap_threshold: int = 15, text_threshold: int = 100) -> Optional[int]:
    """
    Detect the split point between artist name and BPM by finding a significant gap.
    Uses connected components to group text pixels together.
    
    Args:
        combined_region: numpy array image containing both artist and BPM on the same line
        gap_threshold: Minimum pixels for a significant gap (default: 15)
        text_threshold: Pixel intensity threshold for text (default: 100)
        
    Returns:
        x-coordinate where to split, or None if no gap found
    """
    if len(combined_region.shape) == 3:
        gray = cv2.cvtColor(combined_region, cv2.COLOR_RGB2GRAY)
    else:
        gray = combined_region
    
    combined_height, combined_width = combined_region.shape[:2]
    
    # Create binary mask for text (bright pixels)
    _, binary = cv2.threshold(gray, text_threshold, 255, cv2.THRESH_BINARY)
    
    # Use morphological operations to connect nearby text pixels
    kernel = np.ones((3, 3), np.uint8)
    binary_dilated = cv2.dilate(binary, kernel, iterations=1)
    
    # Find connected components
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary_dilated, connectivity=8)
    
    # Get text regions (components with sufficient area)
    text_regions = []
    min_area = 10  # Minimum area for a text region (lowered to catch smaller text)
    
    for i in range(1, num_labels):  # Skip background (label 0)
        area = stats[i, cv2.CC_STAT_AREA]
        if area >= min_area:
            x = stats[i, cv2.CC_STAT_LEFT]
            y = stats[i, cv2.CC_STAT_TOP]
            w = stats[i, cv2.CC_STAT_WIDTH]
            h = stats[i, cv2.CC_STAT_HEIGHT]
            text_regions.append((x, y, x + w, y + h, area))
    
    if len(text_regions) < 2:
        # Not enough text regions found - try with lower threshold
        logger.debug(f"Only found {len(text_regions)} text regions, trying alternative approach")
        # Use horizontal profile method as fallback
        mid_y = combined_height // 2
        horizontal_profile = gray[mid_y, :]
        text_mask = horizontal_profile > text_threshold
        
        # Find the largest gap in the middle portion
        in_gap = False
        gap_start = 0
        max_gap_length = 0
        best_gap_start = None
        
        for i in range(combined_width):
            if not text_mask[i]:  # Background
                if not in_gap:
                    gap_start = i
                    in_gap = True
            else:  # Text
                if in_gap:
                    gap_length = i - gap_start
                    # Look for gaps in the middle portion (20%-70%)
                    if (int(combined_width * 0.20) < gap_start < int(combined_width * 0.70) and 
                        gap_length >= gap_threshold and gap_length > max_gap_length):
                        max_gap_length = gap_length
                        best_gap_start = gap_start
                    in_gap = False
        
        if best_gap_start is not None:
            logger.debug(f"Found gap using horizontal profile at x={best_gap_start} (length={max_gap_length}px)")
            return best_gap_start
        
        return None
    
    # Sort by x position (left to right)
    text_regions.sort(key=lambda r: r[0])
    
    # Find the largest gap between text regions
    # The gap between artist and BPM should be the largest gap
    gaps = []
    for i in range(len(text_regions) - 1):
        gap_start = text_regions[i][2]  # End of left region
        gap_end = text_regions[i+1][0]  # Start of right region
        gap_length = gap_end - gap_start
        
        if gap_length >= gap_threshold:
            gaps.append((gap_start, gap_end, gap_length))
    
    if not gaps:
        return None
    
    # Find the largest gap that's in a reasonable position
    # Should be in the middle portion (20%-70% of width)
    min_split_x = int(combined_width * 0.20)
    max_split_x = int(combined_width * 0.75)
    
    # Sort gaps by length (largest first)
    gaps.sort(key=lambda g: g[2], reverse=True)
    
    # Find the largest gap in the valid range
    for gap_start, gap_end, gap_length in gaps:
        if min_split_x < gap_start < max_split_x:
            logger.debug(f"Found gap at x={gap_start}-{gap_end} (length={gap_length}px)")
            return gap_start
    
    # Fallback: use the largest gap regardless of position
    if gaps:
        gap_start = gaps[0][0]
        logger.debug(f"Found fallback gap at x={gap_start} (length={gaps[0][2]}px)")
        return gap_start
    
    return None


def _extract_bpm_from_text(text: str) -> Optional[int]:
    """
    Extract BPM value from a string.
    
    Args:
        text: Text that may contain BPM information
        
    Returns:
        BPM as integer or None if not found
    """
    if not text:
        return None
    
    # Apply numeric OCR fixes first
    fixed_text = _fix_numeric_ocr(text)
    
    # Common BPM patterns (including decimals)
    patterns = [
        r'\b(\d{2,3}\.?\d?)\s*BPM\b',  # "128 BPM" or "128.5 BPM"
        r'\bBPM\s*:?\s*(\d{2,3}\.?\d?)\b',  # "BPM: 128" or "BPM 128.5"
        r'\b(\d{2,3}\.?\d?)\s*B\s*P\s*M\b',  # "128 B P M" (spaced out)
        r'\b(\d{2,3}\.?\d?)\b',  # Just a number (fallback, less reliable)
    ]
    
    for pattern in patterns:
        match = re.search(pattern, fixed_text, re.IGNORECASE)
        if match:
            try:
                bpm_str = match.group(1)
                # Try to parse as float first to handle decimals
                bpm_float = float(bpm_str)
                # Validate BPM is in reasonable range (60-200)
                if 60 <= bpm_float <= 200:
                    # Return as integer if it's a whole number, otherwise return the float
                    return int(bpm_float) if bpm_float.is_integer() else bpm_float
            except (ValueError, IndexError):
                continue
    
    return None


def _extract_key_from_text(text: str) -> Optional[str]:
    """
    Extract musical key from a string.
    
    Args:
        text: Text that may contain key information
        
    Returns:
        Key as string (e.g., "1A", "12B") or None if not found
    """
    if not text:
        return None
    
    # Apply numeric OCR fixes first
    fixed_text = _fix_numeric_ocr(text)
    
    # Camelot wheel key patterns (1A-12A, 1B-12B)
    camelot_pattern = re.compile(r'\b(1[0-2]|[1-9])[AB]\b', re.IGNORECASE)
    match = camelot_pattern.search(fixed_text)
    if match:
        key = match.group(0).upper()
        # Ensure proper format (e.g., "1A" not "1a")
        if len(key) == 2:
            return key
        elif len(key) == 3:  # "10A", "11A", "12A"
            return key
    
    # Also try pattern that might catch OCR errors like "1O" -> "10B"
    ocr_error_pattern = re.compile(r'\b(1[0-2]|[1-9])([O0])\b', re.IGNORECASE)
    ocr_error_matches = list(ocr_error_pattern.finditer(fixed_text))
    
    # Convert OCR error matches to valid Camelot keys
    for match in ocr_error_matches:
        num = match.group(1)
        letter = match.group(2)
        # If it's "O" or "0", try both A and B
        if letter.upper() in ['O', '0']:
            # Try to determine from context or default to A
            # For now, default to A
            return f"{num}A"
    
    return None


def _fix_numeric_ocr(text: str) -> str:
    """
    Apply conservative OCR fixes for numeric fields (BPM, keys).
    Only fixes common character confusions in numeric contexts.
    
    Args:
        text: Text that may contain numeric values
        
    Returns:
        Text with OCR errors fixed
    """
    # Replace "O" with "0" when inside digit sequences or at boundaries
    text = re.sub(r'(\d)O(\d)', lambda m: m.group(1) + '0' + m.group(2), text)
    text = re.sub(r'(\d)O(\s|$|[^a-zA-Z0-9])', lambda m: m.group(1) + '0' + (m.group(2) or ''), text)
    text = re.sub(r'(^|\s)O(\d)', lambda m: (m.group(1) or '') + '0' + m.group(2), text)
    
    # Replace "l" or "I" with "1" when inside digit sequences or at boundaries
    text = re.sub(r'(\d)[lI](\d)', lambda m: m.group(1) + '1' + m.group(2), text)
    text = re.sub(r'(\d)[lI](\s|$|[^a-zA-Z0-9])', lambda m: m.group(1) + '1' + (m.group(2) or ''), text)
    text = re.sub(r'(^|\s)[lI](\d)', lambda m: (m.group(1) or '') + '1' + m.group(2), text)
    
    return text


def _detect_active_deck_by_play_button(img_array: np.ndarray, coords: Optional[Dict] = None) -> str:
    """
    Detect which deck is active by checking if the play button is green.
    
    Args:
        img_array: Full screenshot as numpy array (RGB)
        coords: Optional coordinates dictionary from region_coordinates.json
        
    Returns:
        "deck1" or "deck2" based on which has a green play button
    """
    # Green color range (RGB values for green play button in djay Pro)
    # Adjust these based on actual green color - typically bright green
    GREEN_MIN = np.array([0, 150, 0])    # Minimum green RGB (low red, medium-high green, low blue)
    GREEN_MAX = np.array([100, 255, 100])  # Maximum green RGB
    
    # Get play button coordinates
    if coords:
        deck1_play = coords.get('deck1_play_button')
        deck2_play = coords.get('deck2_play_button')
    else:
        # Fallback to default coordinates if not found
        logger.warning("Play button coordinates not found, defaulting to deck1")
        return "deck1"
    
    if not deck1_play or not deck2_play:
        logger.warning("Play button coordinates incomplete, defaulting to deck1")
        return "deck1"
    
    def check_play_button_for_green(play_button_bounds):
        """Check if play button region contains green pixels."""
        x_start, y_start, x_end, y_end = play_button_bounds
        
        # Ensure bounds are valid
        height, width = img_array.shape[:2]
        x_start = max(0, min(x_start, width - 1))
        y_start = max(0, min(y_start, height - 1))
        x_end = max(x_start + 1, min(x_end, width))
        y_end = max(y_start + 1, min(y_end, height))
        
        if x_end <= x_start or y_end <= y_start:
            return False
        
        # Extract play button region
        play_button_region = img_array[y_start:y_end, x_start:x_end]
        
        if len(play_button_region.shape) != 3:
            return False
        
        # Create mask for green pixels
        green_mask = cv2.inRange(play_button_region, GREEN_MIN, GREEN_MAX)
        green_pixel_count = np.sum(green_mask > 0)
        total_pixels = play_button_region.shape[0] * play_button_region.shape[1]
        
        if total_pixels == 0:
            return False
        
        green_ratio = green_pixel_count / total_pixels
        
        # If more than 15% of pixels are green, consider it active
        # (adjust threshold based on testing)
        is_green = green_ratio > 0.15
        
        logger.debug(f"Play button green ratio: {green_ratio:.2%}, active: {is_green}")
        
        return is_green
    
    deck1_active = check_play_button_for_green(deck1_play)
    deck2_active = check_play_button_for_green(deck2_play)
    
    # Determine active deck
    if deck1_active and not deck2_active:
        logger.info("Detected active deck: deck1 (green play button)")
        return "deck1"
    elif deck2_active and not deck1_active:
        logger.info("Detected active deck: deck2 (green play button)")
        return "deck2"
    elif deck1_active and deck2_active:
        # Both playing - return the first one (or could handle "both" case)
        logger.info("Both decks appear active, defaulting to deck1")
        return "deck1"
    else:
        # Neither playing - default to deck1
        logger.info("No active deck detected (no green play buttons), defaulting to deck1")
        return "deck1"


def extract_metadata(screenshot: Image.Image) -> Dict[str, Any]:
    """
    Extract track metadata from djay Pro screenshot.
    Uses region-based extraction with coordinates from AudioApis.
    
    Args:
        screenshot: PIL Image of the djay Pro window
        
    Returns:
        Dictionary with deck1, deck2, and active_deck information
    """
    # Convert PIL to numpy array for region extraction
    img_array = np.array(screenshot)
    
    # Get image dimensions
    height, width = img_array.shape[:2]
    logger.info(f"Processing screenshot: {width}x{height} pixels")
    
    # Load region coordinates from file, or use defaults
    coords = _load_region_coordinates()
    if coords:
        # Use coordinates from region_coordinates.json
        deck1_bounds = coords.get('deck1_bounds', [1, 4, 960, 115])
        deck2_bounds = coords.get('deck2_bounds', [964, 2, 1918, 116])
        deck1_x_start, deck1_y_start, deck1_x_end, deck1_y_end = deck1_bounds
        deck2_x_start, deck2_y_start, deck2_x_end, deck2_y_end = deck2_bounds
        logger.info("Using coordinates from region_coordinates.json")
    else:
        # Fallback to default coordinates from AudioApis
        deck1_x_start, deck1_y_start, deck1_x_end, deck1_y_end = 1, 4, 960, 115
        deck2_x_start, deck2_y_start, deck2_x_end, deck2_y_end = 964, 2, 1918, 116
        logger.info("Using default coordinates (region_coordinates.json not found)")
    
    # Extract deck regions using precise bounds
    deck1_region = img_array[deck1_y_start:deck1_y_end, deck1_x_start:deck1_x_end]
    deck2_region = img_array[deck2_y_start:deck2_y_end, deck2_x_start:deck2_x_end]
    
    logger.info(f"Deck 1 region: {deck1_region.shape[1]}x{deck1_region.shape[0]} pixels")
    logger.info(f"Deck 2 region: {deck2_region.shape[1]}x{deck2_region.shape[0]} pixels")
    
    # Extract metadata for each deck using region-based extraction
    deck1_metadata = _extract_deck_metadata_regions(deck1_region, "deck1", coords)
    deck2_metadata = _extract_deck_metadata_regions(deck2_region, "deck2", coords)
    
    # Determine active deck by detecting green play button
    active_deck = _detect_active_deck_by_play_button(img_array, coords)
    
    # Add active status to each deck
    deck1_metadata["active"] = (active_deck == "deck1")
    deck2_metadata["active"] = (active_deck == "deck2")
    
    logger.info(f"Extracted metadata - Deck1: Title={deck1_metadata.get('title')}, Artist={deck1_metadata.get('artist')}, "
                f"BPM={deck1_metadata.get('bpm')}, Key={deck1_metadata.get('key')}, Active={deck1_metadata.get('active')} | "
                f"Deck2: Title={deck2_metadata.get('title')}, Artist={deck2_metadata.get('artist')}, "
                f"BPM={deck2_metadata.get('bpm')}, Key={deck2_metadata.get('key')}, Active={deck2_metadata.get('active')}")
    
    return {
        "deck1": deck1_metadata,
        "deck2": deck2_metadata,
        "active_deck": active_deck,
        "timestamp": None  # Will be set by caller
    }


def _detect_text_regions_by_color(deck_region: np.ndarray) -> Dict[str, Optional[Tuple[int, int, int, int]]]:
    """
    Detect text regions based on color: white for title, grey for artist/BPM.
    Uses spatial relationships: title is white at top, artist/BPM are grey on same line below.
    
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
    # Use morphological operations to connect nearby text
    kernel = np.ones((3, 3), np.uint8)
    white_mask_dilated = cv2.dilate(white_mask.astype(np.uint8) * 255, kernel, iterations=1)
    
    white_components = cv2.connectedComponentsWithStats(white_mask_dilated, connectivity=8)
    num_labels, labels, stats, centroids = white_components
    
    # Find white text regions in the upper portion (title area)
    # Title is typically in the top 40% of the deck
    title_bbox = None
    title_candidates = []
    
    if num_labels > 1:
        for i in range(1, num_labels):
            x = int(stats[i, cv2.CC_STAT_LEFT])
            y = int(stats[i, cv2.CC_STAT_TOP])
            w = int(stats[i, cv2.CC_STAT_WIDTH])
            h = int(stats[i, cv2.CC_STAT_HEIGHT])
            area = int(stats[i, cv2.CC_STAT_AREA])
            
            # Title should be in upper portion and reasonably large
            if y < height * 0.4 and area > 100 and w > 50:
                title_candidates.append((x, y, x + w, y + h, area))
        
        if title_candidates:
            # Sort by y position (topmost first), then by area (largest first)
            title_candidates.sort(key=lambda r: (r[1], -r[4]))
            title_bbox = title_candidates[0][:4]
    
    # Find grey text regions (artist and BPM)
    # They're typically in the middle portion, on the same horizontal line
    grey_mask_dilated = cv2.dilate(grey_mask.astype(np.uint8) * 255, kernel, iterations=1)
    grey_components = cv2.connectedComponentsWithStats(grey_mask_dilated, connectivity=8)
    num_labels_grey, labels_grey, stats_grey, centroids_grey = grey_components
    
    artist_bbox = None
    bpm_bbox = None
    
    if num_labels_grey > 1:
        # Get grey text regions in the middle portion (where artist/BPM are)
        grey_regions = []
        for i in range(1, num_labels_grey):
            x = int(stats_grey[i, cv2.CC_STAT_LEFT])
            y = int(stats_grey[i, cv2.CC_STAT_TOP])
            w = int(stats_grey[i, cv2.CC_STAT_WIDTH])
            h = int(stats_grey[i, cv2.CC_STAT_HEIGHT])
            area = int(stats_grey[i, cv2.CC_STAT_AREA])
            
            # Artist/BPM are typically in middle portion (30-70% of height)
            if height * 0.3 < y < height * 0.7 and area > 50:
                grey_regions.append((x, y, x + w, y + h, area, y + h // 2))  # Add center y
        
        if grey_regions:
            # Group by similar y-level (same horizontal line)
            grey_regions.sort(key=lambda r: (r[5], r[0]))  # Sort by y-center, then x
            
            # Find groups of regions on similar y-levels
            y_tolerance = 10
            current_group = [grey_regions[0]]
            groups = []
            
            for region in grey_regions[1:]:
                if abs(region[5] - current_group[0][5]) < y_tolerance:
                    current_group.append(region)
                else:
                    groups.append(current_group)
                    current_group = [region]
            if current_group:
                groups.append(current_group)
            
            # The largest group on a horizontal line is likely artist + BPM
            if groups:
                # Sort groups by number of regions (most regions = artist + BPM line)
                groups.sort(key=len, reverse=True)
                main_line = groups[0]
                
                if len(main_line) >= 1:
                    # First region is artist (leftmost)
                    artist_bbox = main_line[0][:4]
                
                if len(main_line) >= 2:
                    # Second region is BPM (to the right of artist)
                    bpm_bbox = main_line[1][:4]
                elif len(main_line) == 1:
                    # Only one region - check if it's wide enough to contain both
                    x1, y1, x2, y2 = main_line[0][:4]
                    if (x2 - x1) > width * 0.3:  # Wide enough to be artist + space + BPM
                        # Split it - left part is artist, right part is BPM
                        mid_x = (x1 + x2) // 2
                        artist_bbox = (x1, y1, mid_x, y2)
                        bpm_bbox = (mid_x, y1, x2, y2)
    
    return {
        'title': title_bbox,
        'artist': artist_bbox,
        'bpm': bpm_bbox
    }


def _extract_deck_metadata_regions(deck_region: np.ndarray, deck_name: str, coords: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Extract metadata from a deck using color-based detection for title/artist/BPM,
    falling back to coordinate-based if color detection fails.
    
    Args:
        deck_region: numpy array image for one deck (left or right half)
        deck_name: Name of the deck for logging ("deck1" or "deck2")
        coords: Optional coordinates dictionary from region_coordinates.json
        
    Returns:
        Dictionary with title, artist, bpm, key
    """
    deck_height, deck_width = deck_region.shape[:2]
    
    # Try color-based detection first (DISABLED - using coordinate-based for now)
    color_regions = _detect_text_regions_by_color(deck_region)
    
    # Use color-based regions if detected, otherwise fall back to coordinate-based
    use_color_detection = False  # Disabled - coordinate-based is more accurate
    
    if use_color_detection:
        logger.debug(f"Using color-based detection for {deck_name}")
        # Extract regions using color detection
        title_bbox = color_regions['title']
        artist_bbox = color_regions['artist']
        bpm_bbox = color_regions['bpm']
        
        # Extract title region
        if title_bbox:
            title_x_start, title_y_start, title_x_end, title_y_end = title_bbox
            title_x_start = max(0, title_x_start - REGION_PADDING)
            title_x_end = min(deck_width, title_x_end + REGION_PADDING)
            title_y_start = max(0, title_y_start - REGION_PADDING)
            title_y_end = min(deck_height, title_y_end + REGION_PADDING)
        else:
            title_x_start = title_y_start = title_x_end = title_y_end = 0
        
        # Extract artist region
        if artist_bbox:
            artist_x_start, artist_y_start, artist_x_end, artist_y_end = artist_bbox
            artist_x_start = max(0, artist_x_start - REGION_PADDING)
            artist_x_end = min(deck_width, artist_x_end + REGION_PADDING)
            artist_y_start = max(0, artist_y_start - REGION_PADDING)
            artist_y_end = min(deck_height, artist_y_end + REGION_PADDING)
        else:
            artist_x_start = artist_y_start = artist_x_end = artist_y_end = 0
        
        # Extract BPM region
        if bpm_bbox:
            bpm_x_start, bpm_y_start, bpm_x_end, bpm_y_end = bpm_bbox
            bpm_x_start = max(0, bpm_x_start - REGION_PADDING)
            bpm_x_end = min(deck_width, bpm_x_end + REGION_PADDING)
            bpm_y_start = max(0, bpm_y_start - REGION_PADDING)
            bpm_y_end = min(deck_height, bpm_y_end + REGION_PADDING)
        else:
            bpm_x_start = bpm_y_start = bpm_x_end = bpm_y_end = 0
        
        # For key, use coordinate-based (it's usually in a fixed position)
        if coords:
            deck_regions = coords.get(f'{deck_name}_regions', {})
            key_pct = deck_regions.get('key', {}).get('percentages', {})
            key_x_start = int(deck_width * key_pct.get('x_start', 0.9114))
            key_x_end = int(deck_width * key_pct.get('x_end', 0.9844))
            key_y_start = int(deck_height * key_pct.get('y_start', 0.0541))
            key_y_end = int(deck_height * key_pct.get('y_end', 0.4775))
        else:
            if deck_name == "deck1":
                key_x_start = int(deck_width * 0.9114)
                key_x_end = int(deck_width * 0.9844)
                key_y_start = int(deck_height * 0.0541)
                key_y_end = int(deck_height * 0.4775)
            else:
                key_x_start = int(deck_width * 0.8113)
                key_x_end = int(deck_width * 0.8711)
                key_y_start = int(deck_height * 0.1053)
                key_y_end = int(deck_height * 0.4474)
    else:
        # Fall back to coordinate-based detection
        logger.debug(f"Using coordinate-based detection for {deck_name}")
        if coords:
            deck_regions = coords.get(f'{deck_name}_regions', {})
            if deck_regions:
                # Use percentages from coordinates file
                title_pct = deck_regions.get('title', {}).get('percentages', {})
                title_x_start = int(deck_width * title_pct.get('x_start', 0.1178))
                title_x_end = int(deck_width * title_pct.get('x_end', 0.8081))
                title_y_start = int(deck_height * title_pct.get('y_start', 0.0360))
                title_y_end = int(deck_height * title_pct.get('y_end', 0.3243))
                
                # Get artist y coordinates for height
                artist_pct = deck_regions.get('artist', {}).get('percentages', {})
                artist_y_start = int(deck_height * artist_pct.get('y_start', 0.3750))  # Pixel-perfect to capture all letters
                artist_y_end = int(deck_height * artist_pct.get('y_end', 0.5135))
                
                # Create combined artist+BPM region with same width as title
                # Use title x coordinates for width, artist y coordinates for height
                artist_bpm_x_start = title_x_start  # Same as title start
                artist_bpm_x_end = title_x_end      # Same as title end (same width)
                artist_bpm_y_start = artist_y_start
                artist_bpm_y_end = artist_y_end
                
                key_pct = deck_regions.get('key', {}).get('percentages', {})
                key_x_start = int(deck_width * key_pct.get('x_start', 0.9114))
                key_x_end = int(deck_width * key_pct.get('x_end', 0.9844))
                key_y_start = int(deck_height * key_pct.get('y_start', 0.0541))
                key_y_end = int(deck_height * key_pct.get('y_end', 0.4775))
            else:
                # Fallback to defaults
                if deck_name == "deck1":
                    title_x_start, title_x_end = int(deck_width * 0.1178), int(deck_width * 0.7000)
                    title_y_start, title_y_end = int(deck_height * 0.0360), int(deck_height * 0.2500)
                    artist_y_start = int(deck_height * 0.3423)
                    artist_y_end = int(deck_height * 0.5135)
                    key_x_start, key_x_end = int(deck_width * 0.9114), int(deck_width * 0.9844)
                    key_y_start, key_y_end = int(deck_height * 0.0541), int(deck_height * 0.4775)
                else:
                    title_x_start, title_x_end = int(deck_width * 0.0063), int(deck_width * 0.3000)
                    title_y_start, title_y_end = int(deck_height * 0.0351), int(deck_height * 0.2000)
                    artist_y_start = int(deck_height * 0.3750)  # Pixel-perfect to capture all letters
                    artist_y_end = int(deck_height * 0.5398)
                    key_x_start, key_x_end = int(deck_width * 0.8113), int(deck_width * 0.8711)
                    key_y_start, key_y_end = int(deck_height * 0.1053), int(deck_height * 0.4474)
                
                # Create combined artist+BPM region with same width as title
                artist_bpm_x_start = title_x_start
                artist_bpm_x_end = title_x_end
                artist_bpm_y_start = artist_y_start
                artist_bpm_y_end = artist_y_end
        else:
            # Use default coordinates
            if deck_name == "deck1":
                title_x_start, title_x_end = int(deck_width * 0.1178), int(deck_width * 0.7000)
                title_y_start, title_y_end = int(deck_height * 0.0360), int(deck_height * 0.2500)
                artist_y_start = int(deck_height * 0.3423)
                artist_y_end = int(deck_height * 0.5135)
                key_x_start, key_x_end = int(deck_width * 0.9114), int(deck_width * 0.9844)
                key_y_start, key_y_end = int(deck_height * 0.0541), int(deck_height * 0.4775)
            else:
                title_x_start, title_x_end = int(deck_width * 0.0063), int(deck_width * 0.3000)
                title_y_start, title_y_end = int(deck_height * 0.0351), int(deck_height * 0.2000)
                artist_y_start = int(deck_height * 0.3509)
                artist_y_end = int(deck_height * 0.5263)
                key_x_start, key_x_end = int(deck_width * 0.8113), int(deck_width * 0.8711)
                key_y_start, key_y_end = int(deck_height * 0.1053), int(deck_height * 0.4474)
            
            # Create combined artist+BPM region with same width as title
            artist_bpm_x_start = title_x_start
            artist_bpm_x_end = title_x_end
            artist_bpm_y_start = artist_y_start
            artist_bpm_y_end = artist_y_end
    
    # Expand regions with padding for better OCR accuracy
    # For title, don't add padding on the right (x_end) to avoid capturing artist/BPM
    title_x_start = max(0, title_x_start - REGION_PADDING)
    title_x_end = min(deck_width, title_x_end)  # No padding on right for title
    title_y_start = max(0, title_y_start - REGION_PADDING)
    title_y_end = min(deck_height, title_y_end + REGION_PADDING)
    
    # Combined artist+BPM region (same width as title)
    # No padding on top (y_start) to avoid capturing text from above
    artist_bpm_x_start = max(0, artist_bpm_x_start - REGION_PADDING)
    artist_bpm_x_end = min(deck_width, artist_bpm_x_end + REGION_PADDING)
    artist_bpm_y_start = artist_bpm_y_start  # No padding on top
    artist_bpm_y_end = min(deck_height, artist_bpm_y_end + REGION_PADDING)
    
    key_x_start = max(0, key_x_start - REGION_PADDING)
    key_x_end = min(deck_width, key_x_end + REGION_PADDING)
    key_y_start = max(0, key_y_start - REGION_PADDING)
    key_y_end = min(deck_height, key_y_end + REGION_PADDING)
    
    # Extract regions
    title_region = deck_region[title_y_start:title_y_end, title_x_start:title_x_end]
    artist_bpm_region = deck_region[artist_bpm_y_start:artist_bpm_y_end, artist_bpm_x_start:artist_bpm_x_end]
    key_region = deck_region[key_y_start:key_y_end, key_x_start:key_x_end]
    
    # Convert numpy arrays to PIL Images for ocrmac
    title_image = Image.fromarray(title_region)
    artist_bpm_image = Image.fromarray(artist_bpm_region)
    key_image = Image.fromarray(key_region)
    
    # Extract text from title and key regions
    title = _extract_text_with_ocrmac(title_image, f"{deck_name}_title")
    
    # Extract combined artist+BPM text
    combined_text = _extract_text_with_ocrmac(artist_bpm_image, f"{deck_name}_artist_bpm")
    
    # Parse combined text: find last letter, then number after it
    artist = None
    bpm = None
    
    if combined_text:
        import re
        combined_text = combined_text.strip()
        
        # Find the position of the last letter
        last_letter_pos = -1
        for i in range(len(combined_text) - 1, -1, -1):
            if combined_text[i].isalpha():
                last_letter_pos = i
                break
        
        if last_letter_pos >= 0:
            # Find number after last letter
            remaining_text = combined_text[last_letter_pos + 1:].strip()
            # Match number (with optional decimal)
            number_match = re.search(r'(\d+\.?\d*)', remaining_text)
            
            if number_match:
                # Extract BPM
                bpm_str = number_match.group(1)
                try:
                    bpm_float = float(bpm_str)
                    if 60 <= bpm_float <= 200:
                        bpm = int(bpm_float) if bpm_float.is_integer() else bpm_float
                    else:
                        bpm = None
                except ValueError:
                    bpm = None
                
                # Artist is everything before the number
                number_start = last_letter_pos + 1 + number_match.start()
                artist = combined_text[:number_start].strip()
                # Clean up artist: remove trailing non-alphanumeric characters (except spaces)
                # Keep only letters, numbers, spaces, and common punctuation
                import re
                artist = re.sub(r'[^\w\s\-\.\(\)]+$', '', artist).strip()  # Remove trailing special chars
                artist = re.sub(r'\s+', ' ', artist)  # Normalize whitespace
            else:
                # No number found, use all text as artist
                artist = combined_text.strip()
                bpm = None
        else:
            # No letters found, try to extract number anyway
            number_match = re.search(r'(\d+\.?\d*)', combined_text)
            if number_match:
                bpm_str = number_match.group(1)
                try:
                    bpm_float = float(bpm_str)
                    if 60 <= bpm_float <= 200:
                        bpm = int(bpm_float) if bpm_float.is_integer() else bpm_float
                    else:
                        bpm = None
                except ValueError:
                    bpm = None
                artist = combined_text[:number_match.start()].strip()
            else:
                artist = combined_text.strip()
                bpm = None
    
    # Extract key from key region
    key_text = _extract_text_with_ocrmac(key_image, f"{deck_name}_key")
    key = _extract_key_from_text(key_text) if key_text else None
    
    metadata = {
        "deck": deck_name,
        "title": title,
        "artist": artist,
        "bpm": bpm,
        "key": key
    }
    
    logger.debug(f"Region-based extraction for {deck_name}: title={title}, artist={artist}, bpm={bpm}, key={key}")
    
    return metadata

