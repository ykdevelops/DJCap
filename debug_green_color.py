#!/usr/bin/env python3
"""
Debug script to analyze the actual green color values in play button regions.
Run this when a deck is playing (green button) to see the actual RGB values.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from src.window_capture import capture_djay_window
import json
import numpy as np
import cv2

def analyze_green_colors():
    """Analyze actual green color values in play button regions."""
    print("Capturing djay Pro window...")
    print("Make sure at least one deck is playing (green button visible)")
    print("="*70)
    
    screenshot = capture_djay_window()
    img_array = np.array(screenshot)
    
    # Load coordinates
    with open('data/region_coordinates.json', 'r') as f:
        coords = json.load(f)
    
    deck1_play = coords.get('deck1_play_button')
    deck2_play = coords.get('deck2_play_button')
    
    for deck_name, play_bounds in [("Deck 1", deck1_play), ("Deck 2", deck2_play)]:
        if not play_bounds:
            continue
        
        x_start, y_start, x_end, y_end = play_bounds
        height, width = img_array.shape[:2]
        
        x_start = max(0, min(x_start, width - 1))
        y_start = max(0, min(y_start, height - 1))
        x_end = max(x_start + 1, min(x_end, width))
        y_end = max(y_start + 1, min(y_end, height))
        
        region = img_array[y_start:y_end, x_start:x_end]
        
        if len(region.shape) != 3:
            continue
        
        # Get color statistics
        red_channel = region[:, :, 0]
        green_channel = region[:, :, 1]
        blue_channel = region[:, :, 2]
        
        # Statistics
        min_r, max_r, mean_r = np.min(red_channel), np.max(red_channel), np.mean(red_channel)
        min_g, max_g, mean_g = np.min(green_channel), np.max(green_channel), np.mean(green_channel)
        min_b, max_b, mean_b = np.min(blue_channel), np.max(blue_channel), np.mean(blue_channel)
        
        # Find pixels where green is significantly higher than red and blue
        green_dominant = (green_channel > red_channel + 20) & (green_channel > blue_channel + 20)
        green_pixels = region[green_dominant]
        
        print(f"\n{deck_name} Play Button Region:")
        print(f"  Size: {x_end-x_start} x {y_end-y_start} pixels")
        print(f"  Average RGB: ({mean_r:.1f}, {mean_g:.1f}, {mean_b:.1f})")
        print(f"  RGB Range: R[{min_r}-{max_r}], G[{min_g}-{max_g}], B[{min_b}-{max_b}]")
        
        if len(green_pixels) > 0:
            green_r_min, green_r_max = np.min(green_pixels[:, 0]), np.max(green_pixels[:, 0])
            green_g_min, green_g_max = np.min(green_pixels[:, 1]), np.max(green_pixels[:, 1])
            green_b_min, green_b_max = np.min(green_pixels[:, 2]), np.max(green_pixels[:, 2])
            
            print(f"  Green-dominant pixels: {len(green_pixels)}")
            print(f"  Green pixel RGB range: R[{green_r_min}-{green_r_max}], G[{green_g_min}-{green_g_max}], B[{green_b_min}-{green_b_max}]")
            print(f"  Green pixel avg RGB: ({np.mean(green_pixels[:, 0]):.1f}, {np.mean(green_pixels[:, 1]):.1f}, {np.mean(green_pixels[:, 2]):.1f})")
            
            # Suggested color range
            print(f"\n  Suggested GREEN_MIN: [0, {max(50, int(green_g_min - 20))}, 0]")
            print(f"  Suggested GREEN_MAX: [{min(255, int(green_r_max + 20))}, 255, {min(255, int(green_b_max + 20))}]")
        else:
            print(f"  No green-dominant pixels found (button is likely NOT green/active)")

if __name__ == "__main__":
    try:
        analyze_green_colors()
    except Exception as e:
        import traceback
        print(f"Error: {e}")
        traceback.print_exc()

