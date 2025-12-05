#!/usr/bin/env python3
"""
Test script to debug green color detection.
Shows exactly what the detection code sees.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from src.window_capture import capture_djay_window
from src.metadata_extractor import _load_region_coordinates
import numpy as np
import cv2
import json

def test_green_detection():
    """Test green detection with detailed output."""
    print("="*70)
    print("GREEN COLOR DETECTION TEST")
    print("="*70)
    print("\nMake sure at least one deck is playing (green button visible)")
    print("Press Enter to capture...")
    input()
    
    print("\nCapturing djay Pro window...")
    screenshot = capture_djay_window()
    img_array = np.array(screenshot)
    
    coords = _load_region_coordinates()
    deck1_play = coords.get('deck1_play_button')
    deck2_play = coords.get('deck2_play_button')
    
    # Green color ranges from the code
    GREEN_MIN = np.array([40, 60, 40])
    GREEN_MAX = np.array([180, 255, 180])
    BRIGHT_GREEN_MIN = np.array([100, 150, 100])
    BRIGHT_GREEN_MAX = np.array([150, 255, 150])
    
    print(f"\nGreen color ranges used in code:")
    print(f"  GREEN_MIN: {GREEN_MIN}")
    print(f"  GREEN_MAX: {GREEN_MAX}")
    print(f"  BRIGHT_GREEN_MIN: {BRIGHT_GREEN_MIN}")
    print(f"  BRIGHT_GREEN_MAX: {BRIGHT_GREEN_MAX}")
    
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
        
        total_pixels = region.shape[0] * region.shape[1]
        green_channel = region[:, :, 1]
        red_channel = region[:, :, 0]
        blue_channel = region[:, :, 2]
        
        # Method 1: Color range
        green_mask1 = cv2.inRange(region, GREEN_MIN, GREEN_MAX)
        green_count1 = np.sum(green_mask1 > 0)
        green_ratio1 = green_count1 / total_pixels
        
        # Method 2: Bright green
        green_mask2 = cv2.inRange(region, BRIGHT_GREEN_MIN, BRIGHT_GREEN_MAX)
        green_count2 = np.sum(green_mask2 > 0)
        green_ratio2 = green_count2 / total_pixels
        
        # Method 3: Channel-based
        green_dominant = (green_channel > red_channel + 50) & (green_channel > blue_channel + 50) & (green_channel > 60)
        green_dominant_count = np.sum(green_dominant)
        green_dominant_ratio = green_dominant_count / total_pixels
        
        # Averages
        avg_green = np.mean(green_channel)
        avg_red = np.mean(red_channel)
        avg_blue = np.mean(blue_channel)
        green_advantage = avg_green - max(avg_red, avg_blue)
        
        max_ratio = max(green_ratio1, green_ratio2, green_dominant_ratio)
        is_green = (max_ratio > 0.01) or (green_advantage > 40)
        
        print(f"\n{deck_name} Play Button Analysis:")
        print(f"  Region: ({x_start}, {y_start}) to ({x_end}, {y_end})")
        print(f"  Size: {x_end-x_start} x {y_end-y_start} = {total_pixels} pixels")
        print(f"\n  Average RGB: ({avg_red:.1f}, {avg_green:.1f}, {avg_blue:.1f})")
        print(f"  Green advantage: {green_advantage:.1f} points")
        print(f"\n  Detection Results:")
        print(f"    Method 1 (color range): {green_count1}/{total_pixels} ({green_ratio1:.2%})")
        print(f"    Method 2 (bright green): {green_count2}/{total_pixels} ({green_ratio2:.2%})")
        print(f"    Method 3 (channel-based): {green_dominant_count}/{total_pixels} ({green_dominant_ratio:.2%})")
        print(f"    Max ratio: {max_ratio:.2%}")
        print(f"\n  Thresholds:")
        print(f"    Ratio > 1%: {max_ratio > 0.01} ({max_ratio:.2%} > 0.01)")
        print(f"    Green advantage > 40: {green_advantage > 40} ({green_advantage:.1f} > 40)")
        print(f"\n  RESULT: {'✓ ACTIVE (GREEN)' if is_green else '✗ NOT ACTIVE (NOT GREEN)'}")
        
        # Show actual pixel values
        print(f"\n  Sample pixel values (first 5 green-dominant pixels):")
        green_pixels = region[green_dominant]
        if len(green_pixels) > 0:
            for i, pixel in enumerate(green_pixels[:5]):
                print(f"    Pixel {i+1}: RGB({pixel[0]}, {pixel[1]}, {pixel[2]})")
        else:
            print(f"    No green-dominant pixels found")
            # Show some sample pixels anyway
            sample_pixels = region[::10, ::10].reshape(-1, 3)[:5]
            for i, pixel in enumerate(sample_pixels):
                print(f"    Sample pixel {i+1}: RGB({pixel[0]}, {pixel[1]}, {pixel[2]})")

if __name__ == "__main__":
    try:
        test_green_detection()
    except Exception as e:
        import traceback
        print(f"Error: {e}")
        traceback.print_exc()

