#!/usr/bin/env python3
"""Fix Deck 2 extraction - test title, artist, and BPM regions."""
import numpy as np
from PIL import Image
from window_capture import capture_djay_window
from metadata_extractor import _extract_text_with_ocrmac, _extract_bpm_from_text
import json

screenshot = capture_djay_window()
img_array = np.array(screenshot)

# Extract Deck 2
deck2_x_start, deck2_y_start, deck2_x_end, deck2_y_end = 955, 2, 1918, 113
deck2_region = img_array[deck2_y_start:deck2_y_end, deck2_x_start:deck2_x_end]
deck_height, deck_width = deck2_region.shape[:2]

print(f"Deck 2 size: {deck_width}x{deck_height}\n")

with open('region_coordinates.json', 'r') as f:
    coords = json.load(f)

deck2_regions = coords['deck2_regions']
REGION_PADDING = 15

# Test TITLE region - reduce width and height
print("="*60)
print("Testing TITLE region (reduce x_end and y_end):")
print("="*60)

title_pct = deck2_regions['title']['percentages']
current_x_end = title_pct['x_end']
current_y_end = title_pct['y_end']

for x_end_pct in [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65]:
    for y_end_pct in [0.20, 0.25, 0.30, 0.34]:
        title_x_start = int(deck_width * title_pct['x_start'])
        title_x_end = int(deck_width * x_end_pct)
        title_y_start = int(deck_height * title_pct['y_start'])
        title_y_end = int(deck_height * y_end_pct)
        
        # With left padding only, no right padding
        title_x_start_pad = max(0, title_x_start - REGION_PADDING)
        title_x_end_pad = title_x_end
        title_y_start_pad = max(0, title_y_start - REGION_PADDING)
        title_y_end_pad = min(deck_height, title_y_end + REGION_PADDING)
        
        title_region = deck2_region[title_y_start_pad:title_y_end_pad, title_x_start_pad:title_x_end_pad]
        title_image = Image.fromarray(title_region)
        title_text = _extract_text_with_ocrmac(title_image, "test")
        
        is_perfect = title_text and title_text.strip() == "Hey Ya!"
        is_good = (title_text and 
                   "Hey Ya!" in title_text and 
                   "Outkast" not in title_text and 
                   "79" not in title_text and
                   "70" not in title_text)
        
        if is_perfect:
            status = "✅ PERFECT"
            print(f"{status} x_end={x_end_pct:.2f}, y_end={y_end_pct:.2f}: '{title_text}'")
            print(f"  → PERFECT! Use x_end={x_end_pct:.4f}, y_end={y_end_pct:.4f}\n")
            break
        elif is_good:
            status = "✅"
            print(f"{status} x_end={x_end_pct:.2f}, y_end={y_end_pct:.2f}: '{title_text}'")
    if is_perfect:
        break

# Test ARTIST region
print("="*60)
print("Testing ARTIST region:")
print("="*60)

artist_pct = deck2_regions['artist']['percentages']
artist_x_start = int(deck_width * artist_pct['x_start'])
artist_x_end = int(deck_width * artist_pct['x_end'])
artist_y_start = int(deck_height * artist_pct['y_start'])
artist_y_end = int(deck_height * artist_pct['y_end'])

artist_x_start_pad = max(0, artist_x_start - REGION_PADDING)
artist_x_end_pad = min(deck_width, artist_x_end + REGION_PADDING)
artist_y_start_pad = max(0, artist_y_start - REGION_PADDING)
artist_y_end_pad = min(deck_height, artist_y_end + REGION_PADDING)

artist_region = deck2_region[artist_y_start_pad:artist_y_end_pad, artist_x_start_pad:artist_x_end_pad]
artist_image = Image.fromarray(artist_region)
artist_text = _extract_text_with_ocrmac(artist_image, "test")
print(f"Current artist: '{artist_text}'")
print(f"Expected: 'Outkast'")
print(f"Match: {'✅' if artist_text and 'Outkast' in artist_text and artist_text.strip() == 'Outkast' else '❌'}\n")

# Test BPM region
print("="*60)
print("Testing BPM region:")
print("="*60)

bpm_pct = deck2_regions['bpm']['percentages']
bpm_x_start = int(deck_width * bpm_pct['x_start'])
bpm_x_end = int(deck_width * bpm_pct['x_end'])
bpm_y_start = int(deck_height * bpm_pct['y_start'])
bpm_y_end = int(deck_height * bpm_pct['y_end'])

bpm_x_start_pad = max(0, bpm_x_start - REGION_PADDING)
bpm_x_end_pad = min(deck_width, bpm_x_end + REGION_PADDING)
bpm_y_start_pad = max(0, bpm_y_start - REGION_PADDING)
bpm_y_end_pad = min(deck_height, bpm_y_end + REGION_PADDING)

bpm_region = deck2_region[bpm_y_start_pad:bpm_y_end_pad, bpm_x_start_pad:bpm_x_end_pad]
bpm_image = Image.fromarray(bpm_region)
bpm_text = _extract_text_with_ocrmac(bpm_image, "test")
bpm_value = _extract_bpm_from_text(bpm_text) if bpm_text else None
print(f"BPM text: '{bpm_text}'")
print(f"BPM value: {bpm_value}")
print(f"Expected: 79.5")
print(f"Match: {'✅' if bpm_value == 79.5 or (bpm_text and '79.5' in bpm_text) else '❌'}")

