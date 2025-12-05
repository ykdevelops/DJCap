#!/usr/bin/env python3
"""
Simple tool to define play button coordinates for deck 1 and deck 2.
Uses existing deck coordinates from region_coordinates.json.
"""
import numpy as np
from PIL import Image
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.window_capture import capture_djay_window, DjayProWindowNotFoundError

REGION_COORDINATES_FILE = "data/region_coordinates.json"

class PlayButtonDefiner:
    def __init__(self, screenshot):
        self.screenshot = screenshot
        self.img_array = np.array(screenshot)
        self.full_width = screenshot.size[0]
        self.full_height = screenshot.size[1]
        
        # Load existing deck coordinates
        self.deck1_bounds = None
        self.deck2_bounds = None
        self.load_existing_coordinates()
        
        # Play button regions (4 corners each)
        self.deck1_play_button = {'corners': [], 'color': 'green'}
        self.deck2_play_button = {'corners': [], 'color': 'orange'}
        
        self.current_step = 'deck1_play'
        self.corner_count = 0
        
    def load_existing_coordinates(self):
        """Load existing deck coordinates from region_coordinates.json"""
        if os.path.exists(REGION_COORDINATES_FILE):
            try:
                with open(REGION_COORDINATES_FILE, 'r') as f:
                    coords = json.load(f)
                    self.deck1_bounds = coords.get('deck1_bounds')
                    self.deck2_bounds = coords.get('deck2_bounds')
                    print(f"✓ Loaded existing deck coordinates")
            except Exception as e:
                print(f"Warning: Could not load existing coordinates: {e}")
        else:
            print("Warning: region_coordinates.json not found. Using full screenshot.")
    
    def get_region_bounds(self, corners):
        """Convert 4 corners to bounding box (x_start, y_start, x_end, y_end)"""
        if len(corners) != 4:
            return None
        
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        return (min(xs), min(ys), max(xs), max(ys))
    
    def on_click(self, event):
        """Handle mouse clicks to define regions"""
        if event.inaxes != self.ax:
            return
        
        if event.button != 1:  # Left click only
            return
        
        x, y = int(event.xdata), int(event.ydata)
        corner_names = ['Top-Left', 'Top-Right', 'Bottom-Right', 'Bottom-Left']
        
        if self.current_step == 'deck1_play':
            self.deck1_play_button['corners'].append((x, y))
            self.corner_count += 1
            corner_name = corner_names[self.corner_count - 1]
            print(f"✓ Deck 1 Play Button - Corner {self.corner_count}/4 ({corner_name}): ({x}, {y})")
            
            if self.corner_count == 4:
                self.corner_count = 0
                self.current_step = 'deck2_play'
                print("\n" + "="*70)
                print("✓ Deck 1 play button defined!")
                print("="*70)
                print("\nNow click 4 corners for DECK 2 PLAY BUTTON (orange)")
                print("="*70 + "\n")
                # Redraw to show deck 2 instructions
                self.ax.clear()
                self.draw()
                return
        
        elif self.current_step == 'deck2_play':
            self.deck2_play_button['corners'].append((x, y))
            self.corner_count += 1
            corner_name = corner_names[self.corner_count - 1]
            print(f"✓ Deck 2 Play Button - Corner {self.corner_count}/4 ({corner_name}): ({x}, {y})")
            
            if self.corner_count == 4:
                print("\n✓ Deck 2 play button defined!")
                self.save_coordinates()
                plt.close()
                return
        
        # Redraw after each click to show updated visual feedback
        self.ax.clear()
        self.draw()
    
    def save_coordinates(self):
        """Save play button coordinates to region_coordinates.json"""
        # Load existing coordinates
        coords = {}
        if os.path.exists(REGION_COORDINATES_FILE):
            try:
                with open(REGION_COORDINATES_FILE, 'r') as f:
                    coords = json.load(f)
            except Exception:
                pass
        
        # Add play button coordinates
        if len(self.deck1_play_button['corners']) == 4:
            deck1_bounds = self.get_region_bounds(self.deck1_play_button['corners'])
            coords['deck1_play_button'] = deck1_bounds
            print(f"\nDeck 1 Play Button: {deck1_bounds}")
        
        if len(self.deck2_play_button['corners']) == 4:
            deck2_bounds = self.get_region_bounds(self.deck2_play_button['corners'])
            coords['deck2_play_button'] = deck2_bounds
            print(f"Deck 2 Play Button: {deck2_bounds}")
        
        # Save to file
        os.makedirs(os.path.dirname(REGION_COORDINATES_FILE), exist_ok=True)
        with open(REGION_COORDINATES_FILE, 'w') as f:
            json.dump(coords, f, indent=2)
        
        print(f"\n✓ Saved play button coordinates to {REGION_COORDINATES_FILE}")
    
    def draw(self):
        """Draw the screenshot with instructions"""
        self.fig, self.ax = plt.subplots(figsize=(16, 9))
        self.ax.imshow(self.img_array)
        
        # Draw deck bounds if available
        if self.deck1_bounds:
            x1, y1, x2, y2 = self.deck1_bounds
            rect1 = patches.Rectangle((x1, y1), x2-x1, y2-y1, 
                                     linewidth=2, edgecolor='red', facecolor='none', linestyle='--')
            self.ax.add_patch(rect1)
            self.ax.text(x1, y1-10, 'Deck 1', color='red', fontsize=12, fontweight='bold')
        
        if self.deck2_bounds:
            x1, y1, x2, y2 = self.deck2_bounds
            rect2 = patches.Rectangle((x1, y1), x2-x1, y2-y1, 
                                     linewidth=2, edgecolor='blue', facecolor='none', linestyle='--')
            self.ax.add_patch(rect2)
            self.ax.text(x1, y1-10, 'Deck 2', color='blue', fontsize=12, fontweight='bold')
        
        # Draw existing play button corners with visual feedback
        corner_names = ['Top-Left', 'Top-Right', 'Bottom-Right', 'Bottom-Left']
        
        if self.current_step == 'deck1_play':
            color = 'green'
            corners = self.deck1_play_button['corners']
            deck_name = "DECK 1"
        else:
            color = 'orange'
            corners = self.deck2_play_button['corners']
            deck_name = "DECK 2"
        
        # Draw completed corners with labels
        for i, (x, y) in enumerate(corners):
            # Draw corner point
            self.ax.plot(x, y, 'o', color=color, markersize=15, markeredgewidth=2, 
                        markeredgecolor='white', zorder=10)
            # Label the corner
            self.ax.text(x, y-15, f'{i+1}\n{corner_names[i]}', 
                        color=color, fontsize=10, fontweight='bold',
                        ha='center', va='top',
                        bbox=dict(boxstyle='round,pad=0.3', facecolor='white', 
                                edgecolor=color, alpha=0.9), zorder=11)
            # Draw line to next corner
            if i < len(corners) - 1:
                next_x, next_y = corners[i+1]
                self.ax.plot([x, next_x], [y, next_y], color=color, linewidth=3, 
                           linestyle='--', alpha=0.7, zorder=9)
            elif len(corners) == 4:
                # Close the box by drawing line from last to first corner
                first_x, first_y = corners[0]
                self.ax.plot([x, first_x], [y, first_y], color=color, linewidth=3, 
                           linestyle='--', alpha=0.7, zorder=9)
        
        # Draw bounding box if we have all 4 corners
        if len(corners) == 4:
            xs = [c[0] for c in corners]
            ys = [c[1] for c in corners]
            bbox = patches.Polygon(corners, linewidth=3, edgecolor=color, 
                                  facecolor=color, alpha=0.2, zorder=8)
            self.ax.add_patch(bbox)
        
        # Current step instructions with corner number
        if self.current_step == 'deck1_play':
            current_corner = len(corners) + 1
            if current_corner <= 4:
                corner_name = corner_names[current_corner - 1]
                instruction = f"{deck_name} PLAY BUTTON (GREEN)\n\nClick Corner {current_corner}/4: {corner_name}\n\nOrder: Top-Left → Top-Right → Bottom-Right → Bottom-Left"
            else:
                instruction = f"{deck_name} PLAY BUTTON COMPLETE!\n\nAll 4 corners defined."
        else:
            current_corner = len(corners) + 1
            if current_corner <= 4:
                corner_name = corner_names[current_corner - 1]
                instruction = f"{deck_name} PLAY BUTTON (ORANGE)\n\nClick Corner {current_corner}/4: {corner_name}\n\nOrder: Top-Left → Top-Right → Bottom-Right → Bottom-Left"
            else:
                instruction = f"{deck_name} PLAY BUTTON COMPLETE!\n\nAll 4 corners defined."
        
        # Title with current status
        title_text = f"Define Play Button Coordinates - {deck_name}"
        self.ax.set_title(title_text, fontsize=16, fontweight='bold', pad=20)
        
        # Instructions box
        self.ax.text(0.5, 0.02, instruction, 
                    transform=self.ax.transAxes, 
                    fontsize=14, fontweight='bold',
                    color=color,
                    ha='center', va='bottom',
                    bbox=dict(boxstyle='round,pad=1', facecolor='white', 
                            edgecolor=color, linewidth=3, alpha=0.95), zorder=12)
        
        self.ax.set_xlim(0, self.full_width)
        self.ax.set_ylim(self.full_height, 0)
        self.fig.canvas.mpl_connect('button_press_event', self.on_click)
        plt.tight_layout()
        plt.show(block=True)


def main():
    try:
        print("Capturing djay Pro window...")
        screenshot = capture_djay_window()
        print(f"Screenshot captured: {screenshot.size[0]}x{screenshot.size[1]} pixels\n")
        
        print("="*70)
        print("PLAY BUTTON COORDINATE DEFINITION")
        print("="*70)
        print("\nThis tool will help you define the play button regions.")
        print("The play button turns GREEN when a deck is playing.")
        print("\nInstructions:")
        print("1. Click 4 corners around Deck 1's play button (green)")
        print("2. Click 4 corners around Deck 2's play button (orange)")
        print("\nClick in order: top-left → top-right → bottom-right → bottom-left")
        print("="*70 + "\n")
        
        definer = PlayButtonDefiner(screenshot)
        definer.draw()
        
    except DjayProWindowNotFoundError:
        print("Error: djay Pro window not found. Please ensure djay Pro is running.")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nCancelled by user.")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

