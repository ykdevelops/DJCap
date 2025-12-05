#!/usr/bin/env python3
"""
Show a screenshot with both play button regions highlighted.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from src.window_capture import capture_djay_window
import json
import numpy as np
from PIL import Image, ImageDraw
import matplotlib.pyplot as plt
import matplotlib.patches as patches

def show_play_buttons():
    """Capture screenshot and highlight play button regions."""
    print("Capturing djay Pro window...")
    screenshot = capture_djay_window()
    img_array = np.array(screenshot)
    
    # Load coordinates
    with open('data/region_coordinates.json', 'r') as f:
        coords = json.load(f)
    
    deck1_play = coords.get('deck1_play_button')
    deck2_play = coords.get('deck2_play_button')
    
    if not deck1_play or not deck2_play:
        print("ERROR: Play button coordinates not found")
        return
    
    # Create figure
    fig, ax = plt.subplots(figsize=(16, 9))
    ax.imshow(img_array)
    ax.set_title("Play Button Regions", fontsize=16, fontweight='bold')
    
    # Draw Deck 1 play button
    x1, y1, x2, y2 = deck1_play
    rect1 = patches.Rectangle((x1, y1), x2-x1, y2-y1, 
                             linewidth=4, edgecolor='green', facecolor='green', 
                             alpha=0.3, label='Deck 1 Play Button')
    ax.add_patch(rect1)
    ax.text(x1 + (x2-x1)/2, y1 - 10, 'Deck 1 Play Button', 
           color='green', fontsize=12, fontweight='bold', ha='center',
           bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
    
    # Draw Deck 2 play button
    x1, y1, x2, y2 = deck2_play
    rect2 = patches.Rectangle((x1, y1), x2-x1, y2-y1, 
                             linewidth=4, edgecolor='orange', facecolor='orange', 
                             alpha=0.3, label='Deck 2 Play Button')
    ax.add_patch(rect2)
    ax.text(x1 + (x2-x1)/2, y1 - 10, 'Deck 2 Play Button', 
           color='orange', fontsize=12, fontweight='bold', ha='center',
           bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
    
    # Add legend
    ax.legend(loc='upper right', fontsize=10)
    
    # Add info text
    info_text = f"Deck 1: {deck1_play}\nDeck 2: {deck2_play}"
    ax.text(0.02, 0.98, info_text, 
           transform=ax.transAxes, 
           fontsize=10, 
           verticalalignment='top',
           bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
    
    ax.set_xlim(0, screenshot.size[0])
    ax.set_ylim(screenshot.size[1], 0)
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    try:
        show_play_buttons()
    except Exception as e:
        import traceback
        print(f"Error: {e}")
        traceback.print_exc()

