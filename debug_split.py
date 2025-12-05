#!/usr/bin/env python3
"""Debug the dynamic split detection."""
import numpy as np
from PIL import Image
from window_capture import capture_djay_window
from metadata_extractor import _detect_artist_bpm_split, _extract_text_with_ocrmac, _extract_bpm_from_text
import cv2

screenshot = capture_djay_window()
img_array = np.array(screenshot)

# Test Deck 1
deck1_x_start, deck1_y_start, deck1_x_end, deck1_y_end = 1, 1, 958, 114
deck1_region = img_array[deck1_y_start:deck1_y_end, deck1_x_start:deck1_x_end]
deck_height, deck_width = deck1_region.shape[:2]

# Get combined region
artist_x_start = int(deck_width * 0.1170)
artist_y_start = int(deck_height * 0.3628)
artist_y_end = int(deck_height * 0.5398)
bpm_x_end = int(deck_width * 0.3083)
bpm_y_start = int(deck_height * 0.3333)
bpm_y_end = int(deck_height * 0.5045)

combined_y_start = min(artist_y_start, bpm_y_start)
combined_y_end = max(artist_y_end, bpm_y_end)
combined_x_start = artist_x_start
combined_x_end = bpm_x_end

combined_region = deck1_region[combined_y_start:combined_y_end, combined_x_start:combined_x_end]
combined_image = Image.fromarray(combined_region)
combined_image.save("debug_combined_deck1.png")

print(f"Deck 1 combined region: {combined_x_end - combined_x_start}x{combined_y_end - combined_y_start}")

# Test split detection
split_x = _detect_artist_bpm_split(combined_region)
print(f"Split detected at x={split_x}")

if split_x:
    artist_region = combined_region[:, :split_x]
    bpm_region = combined_region[:, split_x:]
    
    artist_img = Image.fromarray(artist_region)
    bpm_img = Image.fromarray(bpm_region)
    
    artist_img.save("debug_artist_split.png")
    bpm_img.save("debug_bpm_split.png")
    
    artist_text = _extract_text_with_ocrmac(artist_img, "debug_artist")
    bpm_text = _extract_text_with_ocrmac(bpm_img, "debug_bpm")
    bpm_value = _extract_bpm_from_text(bpm_text) if bpm_text else None
    
    print(f"Artist: '{artist_text}'")
    print(f"BPM text: '{bpm_text}'")
    print(f"BPM value: {bpm_value}")

