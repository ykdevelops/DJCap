#!/usr/bin/env python3
"""
Interactive tool to define precise OCR regions for each deck.
Click 4 corners (top-left, top-right, bottom-right, bottom-left) for each region.
"""
import numpy as np
from PIL import Image
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.window_capture import capture_djay_window, DjayProWindowNotFoundError

class RegionDefiner:
    def __init__(self, screenshot):
        self.screenshot = screenshot
        self.img_array = np.array(screenshot)
        self.full_width = screenshot.size[0]
        self.full_height = screenshot.size[1]
        
        # Deck bounds (will extract these first)
        self.deck1_bounds = None
        self.deck2_bounds = None
        
        # Regions for each deck (4 corners each)
        self.deck1_regions = {
            'title': {'corners': [], 'color': 'red'},
            'artist': {'corners': [], 'color': 'green'},
            'bpm': {'corners': [], 'color': 'yellow'},
            'key': {'corners': [], 'color': 'blue'}
        }
        self.deck2_regions = {
            'title': {'corners': [], 'color': 'red'},
            'artist': {'corners': [], 'color': 'green'},
            'bpm': {'corners': [], 'color': 'yellow'},
            'key': {'corners': [], 'color': 'blue'}
        }
        
        self.stage = 'define_decks'  # 'define_decks' or 'define_regions'
        self.current_deck = 'deck1'  # 'deck1' or 'deck2'
        self.current_region = 'title'
        self.corner_names = ['Top-Left', 'Top-Right', 'Bottom-Right', 'Bottom-Left']
        self.current_corner = 0
        self.deck_corners = {'deck1': [], 'deck2': []}
        
        # History for undo functionality
        self.history = []
        
        # Setup matplotlib with larger figure for better precision
        self.fig, self.ax = plt.subplots(figsize=(24, 14))
        self.ax.imshow(self.img_array)
        self.ax.set_title(
            f"📋 STEP 1: Define DECK 1\n"
            f"Click {self.corner_names[self.current_corner]} corner ({self.current_corner + 1}/4)\n"
            f"Order: Top-Left → Top-Right → Bottom-Right → Bottom-Left\n"
            f"\n💡 TIP: Use mouse wheel to zoom, drag to pan. Press 'r' to reset zoom.",
            fontsize=16, fontweight='bold', pad=20
        )
        
        # Connect events
        self.fig.canvas.mpl_connect('button_press_event', self.on_click)
        self.fig.canvas.mpl_connect('scroll_event', self.on_scroll)
        self.fig.canvas.mpl_connect('key_press_event', self.on_key)
        
        # Add instructions text box
        self.instructions_text = None
        
        # Save initial state
        self.save_state()
        
        self.update_display()
        plt.tight_layout()
        plt.show(block=True)
        
        # After window closes, show and save coordinates
        self.show_coordinates()
    
    def on_click(self, event):
        if event.inaxes != self.ax:
            return
        
        if event.xdata is None or event.ydata is None:
            return
        
        x = int(event.xdata)
        y = int(event.ydata)
        
        # Ensure within image bounds
        x = max(0, min(self.full_width - 1, x))
        y = max(0, min(self.full_height - 1, y))
        
        if self.stage == 'define_decks':
            # Save state before making changes
            self.save_state()
            
            # Defining deck regions
            corner_name = self.corner_names[self.current_corner]
            deck_num = self.current_deck[-1]
            print(f"\n🎯 DECK {deck_num.upper()} - Click {self.current_corner + 1}/4: {corner_name} at ({x}, {y})")
            
            self.deck_corners[self.current_deck].append((x, y))
            self.current_corner += 1
            
            if self.current_corner >= 4:
                # Got all 4 corners for this deck
                corners = self.deck_corners[self.current_deck]
                x_coords = [c[0] for c in corners]
                y_coords = [c[1] for c in corners]
                x_min, x_max = min(x_coords), max(x_coords)
                y_min, y_max = min(y_coords), max(y_coords)
                
                if self.current_deck == 'deck1':
                    self.deck1_bounds = (x_min, y_min, x_max, y_max)
                    print(f"\n✅ DECK 1 COMPLETE! Bounds: {self.deck1_bounds}")
                    print("   Moving to Deck 2...\n")
                    self.current_deck = 'deck2'
                    self.current_corner = 0
                    self.update_display()
                    self.fig.canvas.draw()
                else:
                    self.deck2_bounds = (x_min, y_min, x_max, y_max)
                    print(f"\n✅ DECK 2 COMPLETE! Bounds: {self.deck2_bounds}")
                    print("   Moving to region definition...\n")
                    # Move to marking text regions
                    self.stage = 'define_regions'
                    self.current_deck = 'deck1'
                    self.current_region = 'title'
                    self.current_corner = 0
                    self.zoom_to_deck1()
                    self.update_display()
                    self.fig.canvas.draw()
        
        elif self.stage == 'define_regions':
            # Save state before making changes
            self.save_state()
            
            # Marking text regions within current deck
            deck_bounds = self.deck1_bounds if self.current_deck == 'deck1' else self.deck2_bounds
            x1, y1, x2, y2 = deck_bounds
            
            # Convert to relative coordinates within deck
            x_rel = x - x1
            y_rel = y - y1
            
            # Ensure within deck bounds
            deck_width = x2 - x1
            deck_height = y2 - y1
            x_rel = max(0, min(deck_width - 1, x_rel))
            y_rel = max(0, min(deck_height - 1, y_rel))
            
            # Get current regions dict
            regions = self.deck1_regions if self.current_deck == 'deck1' else self.deck2_regions
            
            corner_name = self.corner_names[self.current_corner]
            deck_num = self.current_deck[-1]
            region_name = self.current_region.upper()
            print(f"\n🎯 DECK {deck_num.upper()} - {region_name} - Click {self.current_corner + 1}/4: {corner_name} at ({x_rel}, {y_rel})")
            
            regions[self.current_region]['corners'].append((x_rel, y_rel))
            self.current_corner += 1
            
            if self.current_corner >= 4:
                print(f"\n✅ DECK {deck_num.upper()} - {region_name} COMPLETE!")
                self.current_corner = 0
                
                # Move to next region
                region_order = ['title', 'artist', 'bpm', 'key']
                current_idx = region_order.index(self.current_region)
                if current_idx < len(region_order) - 1:
                    self.current_region = region_order[current_idx + 1]
                    self.update_display()
                    self.fig.canvas.draw()
                else:
                    # Finished all regions for current deck
                    print(f"\n✅ DECK {deck_num.upper()} - ALL REGIONS COMPLETE!")
                    if self.current_deck == 'deck1':
                        # Move to Deck 2
                        print("   Moving to Deck 2 regions...\n")
                        self.current_deck = 'deck2'
                        self.current_region = 'title'
                        self.current_corner = 0
                        self.zoom_to_deck2()
                        self.update_display()
                        self.fig.canvas.draw()
                    else:
                        # All done!
                        print("\n🎉 ALL REGIONS COMPLETE! Saving and closing...\n")
                        self.ax.set_title("🎉 ALL REGIONS COMPLETE!\nSaving coordinates...", 
                                         fontsize=20, fontweight='bold', color='green', pad=20)
                        self.update_display()
                        self.fig.canvas.draw()
                        import time
                        time.sleep(1)
                        plt.close(self.fig)
                        return
        
        # Update display
        self.update_display()
        self.fig.canvas.draw()
    
    def on_scroll(self, event):
        """Handle mouse wheel zoom."""
        if event.inaxes != self.ax:
            return
        
        # Get current limits
        cur_xlim = self.ax.get_xlim()
        cur_ylim = self.ax.get_ylim()
        
        # Get mouse position
        xdata = event.xdata
        ydata = event.ydata
        
        if xdata is None or ydata is None:
            return
        
        # Zoom factor
        if event.button == 'up':
            scale_factor = 0.9
        elif event.button == 'down':
            scale_factor = 1.1
        else:
            return
        
        # Calculate new limits
        new_width = (cur_xlim[1] - cur_xlim[0]) * scale_factor
        new_height = (cur_ylim[0] - cur_ylim[1]) * scale_factor
        
        relx = (cur_xlim[1] - xdata) / (cur_xlim[1] - cur_xlim[0])
        rely = (ydata - cur_ylim[1]) / (cur_ylim[0] - cur_ylim[1])
        
        self.ax.set_xlim([xdata - new_width * (1 - relx), xdata + new_width * relx])
        self.ax.set_ylim([ydata + new_height * (1 - rely), ydata - new_height * rely])
        
        self.fig.canvas.draw()
    
    def save_state(self):
        """Save current state to history for undo."""
        state = {
            'stage': self.stage,
            'current_deck': self.current_deck,
            'current_region': self.current_region,
            'current_corner': self.current_corner,
            'deck_corners': {k: v.copy() for k, v in self.deck_corners.items()},
            'deck1_bounds': self.deck1_bounds,
            'deck2_bounds': self.deck2_bounds,
            'deck1_regions': {
                k: {'corners': v['corners'].copy(), 'color': v['color']} 
                for k, v in self.deck1_regions.items()
            },
            'deck2_regions': {
                k: {'corners': v['corners'].copy(), 'color': v['color']} 
                for k, v in self.deck2_regions.items()
            }
        }
        self.history.append(state)
        # Keep only last 10 states to avoid memory issues
        if len(self.history) > 10:
            self.history.pop(0)
    
    def undo(self):
        """Go back one step."""
        if not self.history:
            print("⚠️  Nothing to undo!")
            return False
        
        # Restore previous state
        state = self.history.pop()
        self.stage = state['stage']
        self.current_deck = state['current_deck']
        self.current_region = state['current_region']
        self.current_corner = state['current_corner']
        self.deck_corners = {k: v.copy() for k, v in state['deck_corners'].items()}
        self.deck1_bounds = state['deck1_bounds']
        self.deck2_bounds = state['deck2_bounds']
        self.deck1_regions = {
            k: {'corners': v['corners'].copy(), 'color': v['color']} 
            for k, v in state['deck1_regions'].items()
        }
        self.deck2_regions = {
            k: {'corners': v['corners'].copy(), 'color': v['color']} 
            for k, v in state['deck2_regions'].items()
        }
        
        # Restore zoom if we have deck bounds
        if self.stage == 'define_regions':
            if self.current_deck == 'deck1' and self.deck1_bounds:
                self.zoom_to_deck1()
            elif self.current_deck == 'deck2' and self.deck2_bounds:
                self.zoom_to_deck2()
        
        print("↩️  Undone! Restored previous state.")
        self.update_display()
        self.fig.canvas.draw()
        return True
    
    def on_key(self, event):
        """Handle keyboard shortcuts."""
        if event.key == 'r' or event.key == 'R':
            # Reset zoom
            self.ax.set_xlim(0, self.full_width)
            self.ax.set_ylim(self.full_height, 0)
            self.fig.canvas.draw()
        elif event.key == 'u' or event.key == 'U':
            # Undo last step
            self.undo()
    
    def zoom_to_deck1(self):
        """Zoom view to Deck 1 region."""
        x1, y1, x2, y2 = self.deck1_bounds
        padding = 50
        self.ax.set_xlim(max(0, x1 - padding), min(self.full_width, x2 + padding))
        self.ax.set_ylim(min(self.full_height, y2 + padding), max(0, y1 - padding))
    
    def zoom_to_deck2(self):
        """Zoom view to Deck 2 region."""
        x1, y1, x2, y2 = self.deck2_bounds
        padding = 50
        self.ax.set_xlim(max(0, x1 - padding), min(self.full_width, x2 + padding))
        self.ax.set_ylim(min(self.full_height, y2 + padding), max(0, y1 - padding))
    
    def get_instructions_text(self):
        """Get current instructions based on stage."""
        controls = "• Mouse wheel: Zoom in/out\n• Drag: Pan when zoomed\n• 'r': Reset zoom\n• 'u': Undo last step"
        
        if self.stage == 'define_decks':
            deck_num = self.current_deck[-1]
            corner_name = self.corner_names[self.current_corner]
            return (
                f"📋 STEP 1: Define DECK {deck_num.upper()}\n"
                f"Click the {corner_name} corner of Deck {deck_num} ({self.current_corner + 1}/4)\n"
                f"\nWhat to do:\n"
                f"• Find the {corner_name.lower()} corner of the deck area\n"
                f"• Click precisely on that corner\n"
                f"\nControls:\n{controls}\n"
                f"\nOrder: Top-Left → Top-Right → Bottom-Right → Bottom-Left"
            )
        else:
            deck_num = self.current_deck[-1]
            region_name = self.current_region.upper()
            corner_name = self.corner_names[self.current_corner]
            
            region_descriptions = {
                'title': 'the song title text (e.g., "Uptown Funk")',
                'artist': 'the artist name text (e.g., "Mark Ronson")',
                'bpm': 'the BPM number (e.g., "115.0")',
                'key': 'the musical key (e.g., "7A")'
            }
            
            return (
                f"📋 STEP 2: Mark {region_name} in DECK {deck_num.upper()}\n"
                f"Click the {corner_name} corner of the {region_name} region ({self.current_corner + 1}/4)\n"
                f"\nWhat to do:\n"
                f"• Find {region_descriptions.get(self.current_region, 'this region')}\n"
                f"• Click the {corner_name.lower()} corner of that text area\n"
                f"• Be precise - only include the text, not surrounding elements\n"
                f"\nControls:\n{controls}\n"
                f"\nOrder: Top-Left → Top-Right → Bottom-Right → Bottom-Left"
            )
    
    def update_display(self):
        self.ax.clear()
        self.ax.imshow(self.img_array)
        
        # Update title with instructions
        instructions = self.get_instructions_text()
        self.ax.set_title(instructions, fontsize=14, fontweight='bold', pad=20)
        
        if self.stage == 'define_decks':
            # Draw deck corners being set
            for deck_name, corners in self.deck_corners.items():
                color = 'red' if deck_name == 'deck1' else 'blue'
                if len(corners) > 0:
                    # Draw partial polygon
                    if len(corners) >= 2:
                        for i in range(len(corners) - 1):
                            self.ax.plot([corners[i][0], corners[i+1][0]],
                                        [corners[i][1], corners[i+1][1]],
                                        color=color, linewidth=2, alpha=0.7, linestyle='--')
                    
                    # Draw corner markers
                    for i, (cx, cy) in enumerate(corners):
                        self.ax.plot(cx, cy, 'o', color=color, markersize=12, 
                                   markeredgewidth=2, alpha=0.9)
                        self.ax.text(cx + 5, cy, f'{i+1}', color=color, 
                                   fontsize=14, fontweight='bold',
                                   bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.9))
                    
                    # Draw polygon if 4 corners
                    if len(corners) == 4:
                        from matplotlib.patches import Polygon
                        poly = Polygon(corners, linewidth=2, edgecolor=color, 
                                      facecolor='none', alpha=0.9)
                        self.ax.add_patch(poly)
                        # Add label
                        x_min = min(c[0] for c in corners)
                        y_min = min(c[1] for c in corners)
                        self.ax.text(x_min, y_min - 10, deck_name.upper(), 
                                   color=color, fontweight='bold', fontsize=16)
        
        elif self.stage == 'define_regions':
            # Show current deck bounds
            deck_bounds = self.deck1_bounds if self.current_deck == 'deck1' else self.deck2_bounds
            x1, y1, x2, y2 = deck_bounds
            from matplotlib.patches import Rectangle
            deck_color = 'red' if self.current_deck == 'deck1' else 'blue'
            deck_rect = Rectangle((x1, y1), x2-x1, y2-y1, 
                                 linewidth=2, edgecolor=deck_color, facecolor='none', alpha=0.5)
            self.ax.add_patch(deck_rect)
            
            # Draw text regions for current deck
            regions = self.deck1_regions if self.current_deck == 'deck1' else self.deck2_regions
            for region, data in regions.items():
                corners = data['corners']
                if len(corners) > 0:
                    # Convert to absolute coordinates
                    abs_corners = [(x1 + x, y1 + y) for x, y in corners]
                    color = data['color']
                    
                    # Draw partial polygon
                    if len(corners) >= 2:
                        for i in range(len(corners) - 1):
                            self.ax.plot([abs_corners[i][0], abs_corners[i+1][0]],
                                        [abs_corners[i][1], abs_corners[i+1][1]],
                                        color=color, linewidth=1.5, alpha=0.7, linestyle='--')
                    
                    # Draw corner markers
                    for i, (cx, cy) in enumerate(abs_corners):
                        self.ax.plot(cx, cy, 'o', color=color, markersize=8, 
                                   markeredgewidth=2, alpha=0.9)
                        self.ax.text(cx + 3, cy - 3, f'{i+1}', color=color, 
                                   fontsize=10, fontweight='bold',
                                   bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.8))
                    
                    # Draw polygon if 4 corners
                    if len(corners) == 4:
                        from matplotlib.patches import Polygon
                        poly = Polygon(abs_corners, linewidth=1.5, edgecolor=color, 
                                      facecolor='none', alpha=0.9)
                        self.ax.add_patch(poly)
                        # Add label
                        x_min = min(c[0] for c in abs_corners)
                        y_min = min(c[1] for c in abs_corners)
                        self.ax.text(x_min, y_min - 5, region.upper(), 
                                   color=color, fontweight='bold', fontsize=12)
            
            # Zoom to current deck
            if self.current_deck == 'deck1':
                self.zoom_to_deck1()
            else:
                self.zoom_to_deck2()
        
        self.ax.grid(True, alpha=0.2, linestyle='--', linewidth=0.3)
        self.ax.set_xlabel('X coordinate (pixels)', fontsize=11)
        self.ax.set_ylabel('Y coordinate (pixels)', fontsize=11)
    
    def show_coordinates(self):
        """Print and save coordinates."""
        import json
        
        print("\n" + "="*80)
        print("REGION COORDINATES")
        print("="*80)
        
        if not self.deck1_bounds or not self.deck2_bounds:
            print("⚠️  Deck bounds not defined!")
            return
        
        # Calculate percentages for each region
        deck1_width = self.deck1_bounds[2] - self.deck1_bounds[0]
        deck1_height = self.deck1_bounds[3] - self.deck1_bounds[1]
        deck2_width = self.deck2_bounds[2] - self.deck2_bounds[0]
        deck2_height = self.deck2_bounds[3] - self.deck2_bounds[1]
        
        output_data = {
            'deck1_bounds': self.deck1_bounds,
            'deck2_bounds': self.deck2_bounds,
            'deck1_regions': {},
            'deck2_regions': {}
        }
        
        print("\nDeck 1 Regions (relative to Deck 1):")
        print("-" * 80)
        for region, data in self.deck1_regions.items():
            corners = data['corners']
            if len(corners) == 4:
                x_coords = [c[0] for c in corners]
                y_coords = [c[1] for c in corners]
                x_min, x_max = min(x_coords), max(x_coords)
                y_min, y_max = min(y_coords), max(y_coords)
                
                x_start_pct = x_min / deck1_width
                x_end_pct = x_max / deck1_width
                y_start_pct = y_min / deck1_height
                y_end_pct = y_max / deck1_height
                
                print(f"{region.upper()}:")
                print(f"  Bounding box: x={x_min}-{x_max}, y={y_min}-{y_max}")
                print(f"  Percentages: x={x_start_pct:.4f}-{x_end_pct:.4f}, y={y_start_pct:.4f}-{y_end_pct:.4f}")
                
                output_data['deck1_regions'][region] = {
                    'corners': corners,
                    'bounding_box': {'x': [x_min, x_max], 'y': [y_min, y_max]},
                    'percentages': {
                        'x_start': x_start_pct,
                        'x_end': x_end_pct,
                        'y_start': y_start_pct,
                        'y_end': y_end_pct
                    }
                }
        
        print("\nDeck 2 Regions (relative to Deck 2):")
        print("-" * 80)
        for region, data in self.deck2_regions.items():
            corners = data['corners']
            if len(corners) == 4:
                x_coords = [c[0] for c in corners]
                y_coords = [c[1] for c in corners]
                x_min, x_max = min(x_coords), max(x_coords)
                y_min, y_max = min(y_coords), max(y_coords)
                
                x_start_pct = x_min / deck2_width
                x_end_pct = x_max / deck2_width
                y_start_pct = y_min / deck2_height
                y_end_pct = y_max / deck2_height
                
                print(f"{region.upper()}:")
                print(f"  Bounding box: x={x_min}-{x_max}, y={y_min}-{y_max}")
                print(f"  Percentages: x={x_start_pct:.4f}-{x_end_pct:.4f}, y={y_start_pct:.4f}-{y_end_pct:.4f}")
                
                output_data['deck2_regions'][region] = {
                    'corners': corners,
                    'bounding_box': {'x': [x_min, x_max], 'y': [y_min, y_max]},
                    'percentages': {
                        'x_start': x_start_pct,
                        'x_end': x_end_pct,
                        'y_start': y_start_pct,
                        'y_end': y_end_pct
                    }
                }
        
        # Save to file
        output_file = 'data/region_coordinates.json'
        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=2)
        print(f"\n✅ Coordinates saved to: {output_file}")
        print("="*80)


if __name__ == "__main__":
    try:
        print("Capturing djay Pro window...")
        screenshot = capture_djay_window()
        print(f"Screenshot captured: {screenshot.size[0]}x{screenshot.size[1]} pixels")
        print("\n" + "="*80)
        print("INSTRUCTIONS:")
        print("="*80)
        print("STEP 1: Define Deck Regions")
        print("  1. Click 4 corners to define Deck 1 (red)")
        print("  2. Click 4 corners to define Deck 2 (blue)")
        print()
        print("STEP 2: Mark Text Regions")
        print("  For each deck, mark 4 corners for:")
        print("  - Title (red)")
        print("  - Artist (green)")
        print("  - BPM (yellow)")
        print("  - Key (blue)")
        print()
        print("The window will show clear prompts for each step!")
        print("="*80)
        print()
        RegionDefiner(screenshot)
    except DjayProWindowNotFoundError as e:
        print(f"Error: {e}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

