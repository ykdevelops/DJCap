#!/usr/bin/env python3
"""Test dynamic detection of space between artist and BPM."""
import numpy as np
from PIL import Image
from window_capture import capture_djay_window
import cv2

screenshot = capture_djay_window()
img_array = np.array(screenshot)

# Extract Deck 1
deck1_x_start, deck1_y_start, deck1_x_end, deck1_y_end = 1, 1, 958, 114
deck1_region = img_array[deck1_y_start:deck1_y_end, deck1_x_start:deck1_x_end]
deck_height, deck_width = deck1_region.shape[:2]

# Get the artist+BPM line region (from coordinates)
# This should be a region that spans from artist start to BPM end
artist_y_start = int(deck_height * 0.3628)
artist_y_end = int(deck_height * 0.5398)
artist_x_start = int(deck_width * 0.1170)  # Start of artist
bpm_x_end = int(deck_width * 0.3083)  # End of BPM

# Combined region containing both artist and BPM
combined_region = deck1_region[artist_y_start:artist_y_end, artist_x_start:bpm_x_end]
combined_height, combined_width = combined_region.shape[:2]

# Convert to grayscale if needed
if len(combined_region.shape) == 3:
    gray = cv2.cvtColor(combined_region, cv2.COLOR_RGB2GRAY)
else:
    gray = combined_region

# Find the middle y-position (where text is)
mid_y = combined_height // 2

# Scan horizontally to find pixel intensity
# Look for a gap (dark pixels) between text regions
horizontal_profile = gray[mid_y, :]

# Threshold to find text pixels (bright = text, dark = background)
text_threshold = 100  # Adjust based on grey text color
text_mask = horizontal_profile > text_threshold

# Find gaps (runs of dark pixels)
# A "significant gap" is a run of dark pixels longer than a threshold
gap_threshold = 15  # Minimum pixels for a significant gap

gaps = []
in_gap = False
gap_start = 0

for i in range(combined_width):
    if not text_mask[i]:  # Dark pixel (background)
        if not in_gap:
            gap_start = i
            in_gap = True
    else:  # Bright pixel (text)
        if in_gap:
            gap_length = i - gap_start
            if gap_length >= gap_threshold:
                gaps.append((gap_start, i, gap_length))
            in_gap = False

# Handle gap at the end
if in_gap:
    gap_length = combined_width - gap_start
    if gap_length >= gap_threshold:
        gaps.append((gap_start, combined_width, gap_length))

# The first significant gap after some text is likely the separator
print(f"Combined region: {combined_width}x{combined_height}")
print(f"Horizontal profile at y={mid_y}:")
print(f"  Text pixels: {np.sum(text_mask)}")
print(f"  Gaps found: {len(gaps)}")

for gap_start, gap_end, gap_length in gaps:
    print(f"  Gap at x={gap_start}-{gap_end} (length={gap_length}px)")

# Visualize
combined_image = Image.fromarray(combined_region)
combined_image.save("combined_artist_bpm.png")

# Try splitting at the first significant gap that's not at the start
if gaps:
    # Skip gap at the start (x=0), find first gap after text starts
    for gap_start, gap_end, gap_length in gaps:
        if gap_start > 10:  # Not at the very start
            split_x = gap_start
            artist_region = combined_region[:, :split_x]
            bpm_region = combined_region[:, split_x:]
            
            artist_img = Image.fromarray(artist_region)
            bpm_img = Image.fromarray(bpm_region)
            
            artist_img.save("dynamic_artist.png")
            bpm_img.save("dynamic_bpm.png")
            
            print(f"\nSplit at x={split_x}")
            print(f"  Artist region: 0-{split_x} (width={split_x})")
            print(f"  BPM region: {split_x}-{combined_width} (width={combined_width - split_x})")
            break
