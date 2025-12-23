#!/bin/bash
#
# Cleanup script for DjCap
# Removes generated data files and debug images that are no longer needed
#

set -e

# Change to project root (two levels up from scripts/utils/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../.."

echo "DjCap Cleanup Script"
echo "===================="
echo ""

# Clean debug folder (keeps scripts, removes images)
if [ -d "scripts/debug" ]; then
    echo "Cleaning debug images..."
    find scripts/debug -name "*.png" -type f -delete
    find scripts/debug -name "*.jpg" -type f -delete
    find scripts/debug -name "*.jpeg" -type f -delete
    echo "  ✓ Removed debug images"
fi

# Clean output JSON files (optional - uncomment if you want to remove them)
# if [ -d "data/output" ]; then
#     echo "Cleaning output JSON files..."
#     rm -f data/output/*.json
#     echo "  ✓ Removed output JSON files"
# fi

# Clean temporary files
echo "Cleaning temporary files..."
find . -name "*.tmp" -type f -delete
find . -name "*.bak" -type f -delete
find . -name "*.swp" -type f -delete
find . -name "*~" -type f -delete
echo "  ✓ Removed temporary files"

# Clean Python cache
echo "Cleaning Python cache..."
find . -type d -name "__pycache__" -exec rm -r {} + 2>/dev/null || true
find . -name "*.pyc" -type f -delete
find . -name "*.pyo" -type f -delete
echo "  ✓ Removed Python cache"

# Clean any remaining images in root
echo "Cleaning images in root directory..."
find . -maxdepth 1 -name "*.png" -type f -delete
find . -maxdepth 1 -name "*.jpg" -type f -delete
find . -maxdepth 1 -name "*.jpeg" -type f -delete
echo "  ✓ Removed root images"

echo ""
echo "Cleanup complete! ✓"
echo ""
echo "Note: Output JSON files in data/output/ were NOT removed."
echo "      Uncomment the relevant section in cleanup.sh if you want to remove them too."

