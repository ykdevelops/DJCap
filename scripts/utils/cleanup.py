#!/usr/bin/env python3
"""
Cleanup script for DjCap
Removes generated data files and debug images that are no longer needed.
"""
import os
import sys
from pathlib import Path

def cleanup():
    """Remove generated files and debug images."""
    # Project root is two levels up from scripts/utils/
    project_root = Path(__file__).parent.parent.parent
    
    print("DjCap Cleanup Script")
    print("=" * 50)
    print()
    
    removed_count = 0
    
    # Clean debug folder images
    debug_dir = project_root / "debug"
    if debug_dir.exists():
        print("Cleaning debug images...")
        image_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff']
        for ext in image_extensions:
            for img_file in debug_dir.glob(f"*{ext}"):
                try:
                    img_file.unlink()
                    removed_count += 1
                    print(f"  ✓ Removed: {img_file.name}")
                except Exception as e:
                    print(f"  ✗ Error removing {img_file.name}: {e}")
    
    # Clean temporary files
    print("\nCleaning temporary files...")
    temp_patterns = ['*.tmp', '*.bak', '*.swp', '*~']
    for pattern in temp_patterns:
        for temp_file in project_root.rglob(pattern):
            try:
                if temp_file.is_file():
                    temp_file.unlink()
                    removed_count += 1
                    print(f"  ✓ Removed: {temp_file.relative_to(project_root)}")
            except Exception as e:
                print(f"  ✗ Error removing {temp_file}: {e}")
    
    # Clean Python cache
    print("\nCleaning Python cache...")
    for pycache_dir in project_root.rglob("__pycache__"):
        try:
            if pycache_dir.is_dir():
                import shutil
                shutil.rmtree(pycache_dir)
                removed_count += 1
                print(f"  ✓ Removed: {pycache_dir.relative_to(project_root)}/")
        except Exception as e:
            print(f"  ✗ Error removing {pycache_dir}: {e}")
    
    # Clean .pyc and .pyo files
    for pyc_file in project_root.rglob("*.pyc"):
        try:
            pyc_file.unlink()
            removed_count += 1
        except Exception:
            pass
    
    for pyo_file in project_root.rglob("*.pyo"):
        try:
            pyo_file.unlink()
            removed_count += 1
        except Exception:
            pass
    
    # Clean any remaining images in root
    print("\nCleaning images in root directory...")
    image_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff']
    for ext in image_extensions:
        for img_file in project_root.glob(f"*{ext}"):
            try:
                img_file.unlink()
                removed_count += 1
                print(f"  ✓ Removed: {img_file.name}")
            except Exception as e:
                print(f"  ✗ Error removing {img_file.name}: {e}")
    
    print()
    print("=" * 50)
    print(f"Cleanup complete! Removed {removed_count} files/directories.")
    print()
    print("Note: Output JSON files in data/output/ were NOT removed.")
    print("      They are needed for the application to function.")
    print("      If you want to remove them, do so manually or modify this script.")


if __name__ == "__main__":
    try:
        cleanup()
    except KeyboardInterrupt:
        print("\n\nCleanup interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nError during cleanup: {e}", file=sys.stderr)
        sys.exit(1)

