#!/usr/bin/env python3
"""Fix Deck 2 artist region - test different x_start values."""
import numpy as np
from PIL import Image
from window_capture import capture_djay_window
from metadata_extractor import _extract_text_with_ocrmac
import json

screenshot = capture_djay_window()
img_array = np.array(screenshot)

deck2_x_start, deck2_y_start, deck2_x_end, deck2_y_end = 955, 2, 1918, 113
deck2_region = img_array[deck2_y_start:deck2_y_end, deck2_x_start:deck2_x_end]
deck_height, deck_width = deck2_region.shape[:2]

with open('region_coordinates.json', 'r') as f:
    coords = json.load(f)

deck2_regions = coords['deck2_regions']
artist_pct = deck2_regions['artist']['percentages']
REGION_PADDING = 15

print("Testing ARTIST region with different x_start values:")
print("="*60)

# Current values
current_x_start = artist_pct['x_start']
current_x_end = artist_pct['x_end']
current_y_start = artist_pct['y_start']
current_y_end = artist_pct['y_end']

print(f"Current: x_start={current_x_start:.4f}, x_end={current_x_end:.4f}")
print(f"Current result: 'mey Ta: Outkast'\n")

# Try increasing x_start to skip "mey Ta: "
for x_start_pct in [0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.12, 0.14]:
    artist_x_start = int(deck_width * x_start_pct)
    artist_x_end = int(deck_width * current_x_end)
    artist_y_start = int(deck_height * current_y_start)
    artist_y_end = int(deck_height * current_y_end)
    
    artist_x_start_pad = max(0, artist_x_start - REGION_PADDING)
    artist_x_end_pad = min(deck_width, artist_x_end + REGION_PADDING)
    artist_y_start_pad = max(0, artist_y_start - REGION_PADDING)
    artist_y_end_pad = min(deck_height, artist_y_end + REGION_PADDING)
    
    artist_region = deck2_region[artist_y_start_pad:artist_y_end_pad, artist_x_start_pad:artist_x_end_pad]
    artist_image = Image.fromarray(artist_region)
    artist_text = _extract_text_with_ocrmac(artist_image, "test")
    
    is_perfect = artist_text and artist_text.strip() == "Outkast"
    is_good = (artist_text and 
               "Outkast" in artist_text and 
               "mey Ta" not in artist_text)
    
    status = "✅ PERFECT" if is_perfect else ("✅" if is_good else "❌")
    print(f"{status} x_start={x_start_pct:.4f}: '{artist_text}'")
    
    if is_perfect:
        print(f"  → PERFECT! Use x_start={x_start_pct:.4f}")
        artist_image.save(f"deck2_artist_{x_start_pct:.4f}.png")
        break

