#!/usr/bin/env python3
"""Save screenshots of all OCR regions for inspection."""
import numpy as np
import json
import os
from PIL import Image
from window_capture import capture_djay_window, DjayProWindowNotFoundError

# Region padding (same as in metadata_extractor)
REGION_PADDING = 15

# Path to region coordinates file
REGION_COORDINATES_FILE = "region_coordinates.json"

def _load_region_coordinates():
    """Load region coordinates from JSON file if it exists."""
    if os.path.exists(REGION_COORDINATES_FILE):
        try:
            with open(REGION_COORDINATES_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Failed to load region coordinates: {e}")
    return None

try:
    screenshot = capture_djay_window()
    print(f"Screenshot captured: {screenshot.size[0]}x{screenshot.size[1]} pixels")
    
    # Convert to numpy array
    img_array = np.array(screenshot)
    height, width = img_array.shape[:2]
    
    # Load region coordinates from file, or use defaults
    coords = _load_region_coordinates()
    if coords:
        deck1_bounds = coords.get('deck1_bounds', [1, 4, 960, 115])
        deck2_bounds = coords.get('deck2_bounds', [964, 2, 1918, 116])
        deck1_x_start, deck1_y_start, deck1_x_end, deck1_y_end = deck1_bounds
        deck2_x_start, deck2_y_start, deck2_x_end, deck2_y_end = deck2_bounds
        print("Using coordinates from region_coordinates.json")
    else:
        # Fallback to default coordinates
        deck1_x_start, deck1_y_start, deck1_x_end, deck1_y_end = 1, 4, 960, 115
        deck2_x_start, deck2_y_start, deck2_x_end, deck2_y_end = 964, 2, 1918, 116
        print("Using default coordinates (region_coordinates.json not found)")
    
    # Extract deck regions
    deck1_region = img_array[deck1_y_start:deck1_y_end, deck1_x_start:deck1_x_end]
    deck2_region = img_array[deck2_y_start:deck2_y_end, deck2_x_start:deck2_x_end]
    
    deck1_height, deck1_width = deck1_region.shape[:2]
    deck2_height, deck2_width = deck2_region.shape[:2]
    
    print(f"\nDeck 1 region: {deck1_width}x{deck1_height} pixels")
    print(f"Deck 2 region: {deck2_width}x{deck2_height} pixels")
    
    # Load region coordinates from file if available
    if coords:
        deck1_regions_data = coords.get('deck1_regions', {})
        deck2_regions_data = coords.get('deck2_regions', {})
        
        # Build region dictionaries from percentages
        deck1_regions = {}
        for region_name in ['title', 'artist', 'bpm', 'key']:
            region_data = deck1_regions_data.get(region_name, {})
            pct = region_data.get('percentages', {})
            deck1_regions[region_name] = {
                'x_start': int(deck1_width * pct.get('x_start', 0)),
                'x_end': int(deck1_width * pct.get('x_end', 1)),
                'y_start': int(deck1_height * pct.get('y_start', 0)),
                'y_end': int(deck1_height * pct.get('y_end', 1))
            }
        
        deck2_regions = {}
        for region_name in ['title', 'artist', 'bpm', 'key']:
            region_data = deck2_regions_data.get(region_name, {})
            pct = region_data.get('percentages', {})
            deck2_regions[region_name] = {
                'x_start': int(deck2_width * pct.get('x_start', 0)),
                'x_end': int(deck2_width * pct.get('x_end', 1)),
                'y_start': int(deck2_height * pct.get('y_start', 0)),
                'y_end': int(deck2_height * pct.get('y_end', 1))
            }
    else:
        # Fallback to default coordinates
        deck1_regions = {
            'title': {
                'x_start': int(deck1_width * 0.1178),
                'x_end': int(deck1_width * 0.8081),
                'y_start': int(deck1_height * 0.0360),
                'y_end': int(deck1_height * 0.3243)
            },
            'artist': {
                'x_start': int(deck1_width * 0.1157),
                'x_end': int(deck1_width * 0.2440),
                'y_start': int(deck1_height * 0.3423),
                'y_end': int(deck1_height * 0.5135)
            },
            'bpm': {
                'x_start': int(deck1_width * 0.2544),
                'x_end': int(deck1_width * 0.3045),
                'y_start': int(deck1_height * 0.3333),
                'y_end': int(deck1_height * 0.5045)
            },
            'key': {
                'x_start': int(deck1_width * 0.9114),
                'x_end': int(deck1_width * 0.9844),
                'y_start': int(deck1_height * 0.0541),
                'y_end': int(deck1_height * 0.4775)
            }
        }
        
        deck2_regions = {
            'title': {
                'x_start': int(deck2_width * 0.0063),
                'x_end': int(deck2_width * 0.6939),
                'y_start': int(deck2_height * 0.0351),
                'y_end': int(deck2_height * 0.3333)
            },
            'artist': {
                'x_start': int(deck2_width * 0.0073),
                'x_end': int(deck2_width * 0.1719),
                'y_start': int(deck2_height * 0.3509),
                'y_end': int(deck2_height * 0.5263)
            },
            'bpm': {
                'x_start': int(deck2_width * 0.1771),
                'x_end': int(deck2_width * 0.2275),
                'y_start': int(deck2_height * 0.3333),
                'y_end': int(deck2_height * 0.5175)
            },
            'key': {
                'x_start': int(deck2_width * 0.8113),
                'x_end': int(deck2_width * 0.8711),
                'y_start': int(deck2_height * 0.1053),
                'y_end': int(deck2_height * 0.4474)
            }
        }
    
    # Save Deck 1 regions (no padding)
    print("\n=== Deck 1 Regions ===")
    
    # Title region (no padding)
    title_coords = deck1_regions['title']
    title_x_start = title_coords['x_start']
    title_x_end = title_coords['x_end']
    title_y_start = title_coords['y_start']
    title_y_end = title_coords['y_end']
    title_region = deck1_region[title_y_start:title_y_end, title_x_start:title_x_end]
    title_image = Image.fromarray(title_region)
    title_image.save("deck1_title.png")
    print(f"Saved deck1_title.png: {title_image.size[0]}x{title_image.size[1]} pixels (coords: x={title_x_start}-{title_x_end}, y={title_y_start}-{title_y_end})")
    
    # Combined artist+BPM region (same width as title, no padding)
    artist_coords = deck1_regions['artist']
    artist_bpm_x_start = title_x_start  # Same as title start
    artist_bpm_x_end = title_x_end      # Same as title end
    artist_bpm_y_start = artist_coords['y_start']
    artist_bpm_y_end = artist_coords['y_end']
    artist_bpm_region = deck1_region[artist_bpm_y_start:artist_bpm_y_end, artist_bpm_x_start:artist_bpm_x_end]
    artist_bpm_image = Image.fromarray(artist_bpm_region)
    artist_bpm_image.save("deck1_artist_bpm.png")
    print(f"Saved deck1_artist_bpm.png: {artist_bpm_image.size[0]}x{artist_bpm_image.size[1]} pixels (coords: x={artist_bpm_x_start}-{artist_bpm_x_end}, y={artist_bpm_y_start}-{artist_bpm_y_end})")
    
    # Key region (no padding)
    key_coords = deck1_regions['key']
    key_x_start = key_coords['x_start']
    key_x_end = key_coords['x_end']
    key_y_start = key_coords['y_start']
    key_y_end = key_coords['y_end']
    key_region = deck1_region[key_y_start:key_y_end, key_x_start:key_x_end]
    key_image = Image.fromarray(key_region)
    key_image.save("deck1_key.png")
    print(f"Saved deck1_key.png: {key_image.size[0]}x{key_image.size[1]} pixels (coords: x={key_x_start}-{key_x_end}, y={key_y_start}-{key_y_end})")
    
    # Save Deck 2 regions (no padding)
    print("\n=== Deck 2 Regions ===")
    
    # Title region (no padding)
    title_coords = deck2_regions['title']
    title_x_start = title_coords['x_start']
    title_x_end = title_coords['x_end']
    title_y_start = title_coords['y_start']
    title_y_end = title_coords['y_end']
    title_region = deck2_region[title_y_start:title_y_end, title_x_start:title_x_end]
    title_image = Image.fromarray(title_region)
    title_image.save("deck2_title.png")
    print(f"Saved deck2_title.png: {title_image.size[0]}x{title_image.size[1]} pixels (coords: x={title_x_start}-{title_x_end}, y={title_y_start}-{title_y_end})")
    
    # Combined artist+BPM region (same width as title, no padding)
    artist_coords = deck2_regions['artist']
    artist_bpm_x_start = title_x_start  # Same as title start
    artist_bpm_x_end = title_x_end      # Same as title end
    artist_bpm_y_start = artist_coords['y_start']
    artist_bpm_y_end = artist_coords['y_end']
    artist_bpm_region = deck2_region[artist_bpm_y_start:artist_bpm_y_end, artist_bpm_x_start:artist_bpm_x_end]
    artist_bpm_image = Image.fromarray(artist_bpm_region)
    artist_bpm_image.save("deck2_artist_bpm.png")
    print(f"Saved deck2_artist_bpm.png: {artist_bpm_image.size[0]}x{artist_bpm_image.size[1]} pixels (coords: x={artist_bpm_x_start}-{artist_bpm_x_end}, y={artist_bpm_y_start}-{artist_bpm_y_end})")
    
    # Key region (no padding)
    key_coords = deck2_regions['key']
    key_x_start = key_coords['x_start']
    key_x_end = key_coords['x_end']
    key_y_start = key_coords['y_start']
    key_y_end = key_coords['y_end']
    key_region = deck2_region[key_y_start:key_y_end, key_x_start:key_x_end]
    key_image = Image.fromarray(key_region)
    key_image.save("deck2_key.png")
    print(f"Saved deck2_key.png: {key_image.size[0]}x{key_image.size[1]} pixels (coords: x={key_x_start}-{key_x_end}, y={key_y_start}-{key_y_end})")
    
    # Also save full deck regions for reference
    print("\n=== Full Deck Regions ===")
    deck1_full = Image.fromarray(deck1_region)
    deck1_full.save("deck1_full.png")
    print(f"Saved deck1_full.png: {deck1_full.size[0]}x{deck1_full.size[1]} pixels")
    
    deck2_full = Image.fromarray(deck2_region)
    deck2_full.save("deck2_full.png")
    print(f"Saved deck2_full.png: {deck2_full.size[0]}x{deck2_full.size[1]} pixels")
    
    print("\n✅ All region screenshots saved!")
    
except DjayProWindowNotFoundError as e:
    print(f"Error: {e}")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

