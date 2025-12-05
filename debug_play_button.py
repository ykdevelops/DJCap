#!/usr/bin/env python3
"""
Debug script to test play button detection for both decks.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from src.window_capture import capture_djay_window
from src.metadata_extractor import _detect_active_deck_by_play_button, _load_region_coordinates
import numpy as np
from PIL import Image
import cv2

def debug_play_button_detection():
    """Debug play button detection for both decks."""
    print("Capturing djay Pro window...")
    screenshot = capture_djay_window()
    img_array = np.array(screenshot)
    
    coords = _load_region_coordinates()
    
    if not coords:
        print("ERROR: Could not load coordinates")
        return
    
    deck1_play = coords.get('deck1_play_button')
    deck2_play = coords.get('deck2_play_button')
    
    print(f"\nDeck 1 play button coordinates: {deck1_play}")
    print(f"Deck 2 play button coordinates: {deck2_play}")
    
    # Analyze each play button region
    for deck_name, play_bounds in [("Deck 1", deck1_play), ("Deck 2", deck2_play)]:
        if not play_bounds:
            print(f"\n{deck_name}: No coordinates found")
            continue
        
        x_start, y_start, x_end, y_end = play_bounds
        height, width = img_array.shape[:2]
        
        # Ensure bounds are valid
        x_start = max(0, min(x_start, width - 1))
        y_start = max(0, min(y_start, height - 1))
        x_end = max(x_start + 1, min(x_end, width))
        y_end = max(y_start + 1, min(y_end, height))
        
        print(f"\n{deck_name} Play Button Analysis:")
        print(f"  Region: ({x_start}, {y_start}) to ({x_end}, {y_end})")
        print(f"  Size: {x_end - x_start} x {y_end - y_start} pixels")
        
        play_button_region = img_array[y_start:y_end, x_start:x_end]
        
        if len(play_button_region.shape) != 3:
            print(f"  ERROR: Region is not RGB (shape: {play_button_region.shape})")
            continue
        
        # Get color statistics
        green_channel = play_button_region[:, :, 1]
        red_channel = play_button_region[:, :, 0]
        blue_channel = play_button_region[:, :, 2]
        
        # Method 1: Standard green range
        GREEN_MIN = np.array([0, 150, 0])
        GREEN_MAX = np.array([100, 255, 100])
        green_mask = cv2.inRange(play_button_region, GREEN_MIN, GREEN_MAX)
        green_pixel_count = np.sum(green_mask > 0)
        total_pixels = play_button_region.shape[0] * play_button_region.shape[1]
        green_ratio = green_pixel_count / total_pixels
        
        # Method 2: Bright green
        bright_green_mask = (green_channel > 200) & (red_channel < 100) & (blue_channel < 100)
        bright_green_count = np.sum(bright_green_mask)
        bright_green_ratio = bright_green_count / total_pixels
        
        # Color statistics
        avg_r = np.mean(red_channel)
        avg_g = np.mean(green_channel)
        avg_b = np.mean(blue_channel)
        
        print(f"  Average RGB: ({avg_r:.1f}, {avg_g:.1f}, {avg_b:.1f})")
        print(f"  Green pixels (method 1): {green_pixel_count}/{total_pixels} ({green_ratio:.2%})")
        print(f"  Bright green pixels (method 2): {bright_green_count}/{total_pixels} ({bright_green_ratio:.2%})")
        print(f"  Method 1 active (>10%): {green_ratio > 0.10}")
        print(f"  Method 2 active (>5%): {bright_green_ratio > 0.05}")
        print(f"  Overall active: {green_ratio > 0.10 or bright_green_ratio > 0.05}")
    
    # Test the actual detection function
    print("\n" + "="*70)
    print("Testing _detect_active_deck_by_play_button function:")
    print("="*70)
    active_deck = _detect_active_deck_by_play_button(img_array, coords)
    print(f"\nDetected active deck: {active_deck}")

if __name__ == "__main__":
    try:
        debug_play_button_detection()
    except Exception as e:
        import traceback
        print(f"Error: {e}")
        traceback.print_exc()

