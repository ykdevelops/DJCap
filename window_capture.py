"""
Window capture module for capturing the djay Pro application window.
Based on AudioApis implementation.
"""
import logging
import subprocess
import re
from PIL import Image
import mss

logger = logging.getLogger(__name__)

# Try to import Core Graphics via pyobjc for direct window capture
try:
    from Quartz import (
        CGWindowListCopyWindowInfo,
        kCGWindowListOptionOnScreenOnly,
        kCGWindowListExcludeDesktopElements,
        CGWindowListCreateImage,
        kCGWindowListOptionIncludingWindow,
        kCGWindowImageDefault,
        CGRectMake
    )
    from AppKit import NSBitmapImageRep, NSImage
    CG_AVAILABLE = True
except ImportError:
    logger.debug("pyobjc-framework-Quartz not available, will use mss fallback")
    CG_AVAILABLE = False


class DjayProWindowNotFoundError(Exception):
    """Raised when djay Pro window cannot be found."""
    pass


def _get_djay_window_id_via_cgwindow() -> int | None:
    """
    Get the window ID of the djay Pro window using Core Graphics.
    
    Returns:
        Window ID (CGWindowID) or None if not found
    """
    if not CG_AVAILABLE:
        return None
    
    try:
        # Get list of all on-screen windows
        window_list = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements,
            0
        )
        
        # Process names to try
        process_names = [
            "djay Pro", "djayPro", "Djay Pro", "DjayPro",
            "djay Pro AI", "djayProAI", "Djay Pro AI", "DjayProAI", "djay"
        ]
        
        for window_info in window_list:
            owner_name = window_info.get('kCGWindowOwnerName', '')
            window_name = window_info.get('kCGWindowName', '')
            window_id = window_info.get('kCGWindowNumber', None)
            
            # Check if this window belongs to djay Pro
            for process_name in process_names:
                if owner_name == process_name or process_name.lower() in owner_name.lower():
                    if window_id is not None:
                        logger.debug(f"Found window ID {window_id} for '{owner_name}' (window: '{window_name}')")
                        return window_id
        
        return None
    except Exception as e:
        logger.debug(f"Failed to get window ID via CGWindow: {e}")
        return None


def _get_djay_window_bounds_via_applescript() -> tuple[int, int, int, int] | None:
    """
    Find the djay Pro window bounds using AppleScript on macOS.
    Tries multiple process name variations.
    
    NOTE: This function uses System Events which only queries window information
    and does NOT activate or bring windows to foreground. It is safe to run
    in the background without interrupting the user's workflow.
    
    Returns:
        tuple: (x, y, width, height) of the window, or None if not found
    """
    # Quick check: see if any djay process exists at all
    try:
        quick_check = subprocess.run(
            ['pgrep', '-i', 'djay'],
            capture_output=True,
            timeout=0.5
        )
        if quick_check.returncode != 0:
            logger.debug("No djay process found via pgrep")
            return None
    except (subprocess.TimeoutExpired, Exception) as e:
        logger.debug(f"Quick check failed: {e}")
        # Continue anyway
    
    # Try multiple process name variations in order
    # Most common first for faster detection
    process_names = [
        "djay Pro",  # Most common - exact match from ps output
        "djayPro",
        "Djay Pro",
        "DjayPro",
        "djay Pro AI",
        "djayProAI",
        "Djay Pro AI",
        "DjayProAI",
        "djay"  # Last resort
    ]
    
    for process_name in process_names:
        try:
            # Use position and size instead of bounds (more reliable for some apps)
            # Also check if window is minimized or not visible
            applescript = f'''
            tell application "System Events"
              tell process "{process_name}"
                try
                  set windowCount to count of windows
                  if windowCount = 0 then
                    return ""
                  end if
                  
                  -- Check if window is minimized
                  set isMinimized to value of attribute "AXMinimized" of window 1
                  if isMinimized then
                    return ""
                  end if
                  
                  -- Get position and size (more reliable than bounds for djay Pro)
                  -- Position gives top-left corner, size gives width and height
                  set pos to position of window 1
                  set sz to size of window 1
                  
                  set leftPos to item 1 of pos
                  set topPos to item 2 of pos
                  set winWidth to item 1 of sz
                  set winHeight to item 2 of sz
                  
                  return leftPos & "," & topPos & "," & winWidth & "," & winHeight
                on error
                  return ""
                end try
              end tell
            end tell
            '''
            
            result = subprocess.run(
                ['osascript', '-e', applescript],
                capture_output=True,
                text=True,
                timeout=2  # Reduced timeout for faster failure
            )
            
            if result.returncode != 0:
                error_msg = result.stderr.strip() if result.stderr else "Unknown error"
                logger.debug(f"AppleScript failed for '{process_name}': {error_msg}")
                # Check if it's a permissions error
                if "assistive access" in error_msg.lower() or "-25211" in error_msg:
                    logger.warning(f"Assistive access permission required for '{process_name}'. Please grant Terminal/iTerm/VS Code permission in System Settings > Privacy & Security > Accessibility")
                continue
            
            output = result.stdout.strip()
            logger.debug(f"AppleScript raw output for '{process_name}': {output!r}")
            
            if not output:
                continue
            
            # Parse the result
            try:
                # Extract all integers (including negative) from the output
                # Pattern matches optional minus sign followed by digits
                nums = [int(n) for n in re.findall(r"-?\d+", output)]
                
                if len(nums) == 4:
                    # Format is: x, y, width, height (from position and size)
                    x, y, width, height = nums[0], nums[1], nums[2], nums[3]
                    
                    if width <= 0 or height <= 0:
                        logger.warning(f"Parsed non positive window size from AppleScript output: {output}")
                        continue
                    
                    logger.info(f"Found djay Pro window at ({x}, {y}) with size {width}x{height}")
                    return (x, y, width, height)
                else:
                    logger.warning(f"Unexpected AppleScript output format, found numbers {nums} from: {output}")
                    continue
            except Exception as e:
                logger.warning(f"Failed to parse window bounds: {output}, error: {e}")
                continue
            
        except subprocess.TimeoutExpired:
            logger.debug(f"AppleScript timed out for '{process_name}'")
            continue
        except Exception as e:
            logger.debug(f"Error trying process '{process_name}': {e}")
            continue
    
    # If we get here, none of the process names worked
    logger.warning("djay Pro window not found via AppleScript (tried: %s)", ", ".join(process_names))
    return None


def _find_monitor_for_window(window_bounds: tuple, monitors: list) -> dict:
    """
    Find which monitor contains the window.
    
    Args:
        window_bounds: (x, y, width, height) of the window
        monitors: List of monitor dicts from mss
        
    Returns:
        Monitor dict that contains the window, or None
    """
    x, y, width, height = window_bounds
    window_center_x = x + width // 2
    window_center_y = y + height // 2
    
    # Check each monitor (skip index 0 which is all monitors combined)
    for i in range(1, len(monitors)):
        monitor = monitors[i]
        if (monitor["left"] <= window_center_x <= monitor["left"] + monitor["width"] and
            monitor["top"] <= window_center_y <= monitor["top"] + monitor["height"]):
            logger.debug(f"Window found on monitor {i}: {monitor}")
            return monitor
    
    # If not found, use the monitor that contains the most of the window
    best_monitor = None
    best_overlap = 0
    
    for i in range(1, len(monitors)):
        monitor = monitors[i]
        # Calculate overlap
        overlap_x = max(0, min(x + width, monitor["left"] + monitor["width"]) - max(x, monitor["left"]))
        overlap_y = max(0, min(y + height, monitor["top"] + monitor["height"]) - max(y, monitor["top"]))
        overlap = overlap_x * overlap_y
        
        if overlap > best_overlap:
            best_overlap = overlap
            best_monitor = monitor
    
    if best_monitor:
        logger.debug(f"Window overlaps with monitor: {best_monitor}")
        return best_monitor
    
    # Fallback to primary monitor
    if len(monitors) > 1:
        logger.warning("Could not determine monitor, using primary")
        return monitors[1]
    
    return None


def _capture_window_via_cgwindow(window_id: int, window_bounds: tuple[int, int, int, int]) -> Image.Image | None:
    """
    Capture window content directly using Core Graphics (bypasses windows in front).
    
    Args:
        window_id: CGWindowID of the window
        window_bounds: (x, y, width, height) of the window
        
    Returns:
        PIL Image or None if capture fails
    """
    if not CG_AVAILABLE:
        return None
    
    try:
        x, y, width, height = window_bounds
        
        # Create image of the specific window
        # kCGWindowListOptionIncludingWindow = 0x00000001
        # This captures the window even if it's behind other windows
        # CGRect needs to be in screen coordinates
        # Try to use opaque option if available
        try:
            from Quartz import kCGWindowImageShouldBeOpaque
            image_option = kCGWindowImageShouldBeOpaque
        except ImportError:
            image_option = kCGWindowImageDefault
        
        cg_image = CGWindowListCreateImage(
            CGRectMake(x, y, width, height),  # Full window bounds in screen coordinates
            kCGWindowListOptionIncludingWindow,
            window_id,
            image_option
        )
        
        if cg_image is None:
            logger.debug(f"CGWindowListCreateImage returned None for window {window_id}")
            return None
        
        # Get image dimensions using CGImageGetWidth/Height functions
        from Quartz import CGImageGetWidth, CGImageGetHeight
        width = int(CGImageGetWidth(cg_image))
        height = int(CGImageGetHeight(cg_image))
        
        if width <= 0 or height <= 0:
            logger.debug(f"Invalid window dimensions: {width}x{height}")
            return None
        
        # Convert CGImage to NSImage, then to PIL Image
        # Use a bitmap context to ensure we get RGB (no transparency)
        from Quartz import (
            CGColorSpaceCreateDeviceRGB, CGBitmapContextCreate, CGContextDrawImage,
            kCGImageAlphaPremultipliedLast, kCGBitmapByteOrder32Big
        )
        
        color_space = CGColorSpaceCreateDeviceRGB()
        bytes_per_pixel = 4
        bytes_per_row = bytes_per_pixel * width
        bitmap_info = kCGBitmapByteOrder32Big | kCGImageAlphaPremultipliedLast
        
        # Create context with RGBA
        import ctypes
        buffer = ctypes.create_string_buffer(bytes_per_row * height)
        
        context = CGBitmapContextCreate(
            buffer,
            width,
            height,
            8,  # bits per component
            bytes_per_row,
            color_space,
            bitmap_info
        )
        
        if context is None:
            raise Exception("Failed to create bitmap context")
        
        # Draw the image into the context
        CGContextDrawImage(context, CGRectMake(0, 0, width, height), cg_image)
        
        # Convert RGBA buffer to PIL Image
        img = Image.frombytes('RGBA', (width, height), buffer.raw, 'raw', 'BGRA', bytes_per_row)
        
        # Composite onto white background to remove transparency
        background = Image.new('RGB', img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3])  # Use alpha channel as mask
        img = background
        
        logger.info(f"Captured full window {window_id} directly via CGWindow: {img.size[0]}x{img.size[1]} pixels (mode: {img.mode})")
        return img
        
    except Exception as e:
        logger.debug(f"CGWindow capture failed: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return None


def capture_djay_window() -> Image.Image:
    """
    Capture the full djay Pro window.
    
    This function operates entirely in the background without stealing focus:
    - First tries to capture window content directly (bypasses windows in front)
    - Falls back to mss if direct capture not available
    - Works across multiple monitors
    - Only queries window bounds (does not activate windows)
    - Safe to call repeatedly while DJing without interruption
    - Works even if window is on a different screen
    
    Returns:
        PIL.Image.Image: Screenshot of the full djay Pro window
        
    Raises:
        DjayProWindowNotFoundError: If djay Pro window is not found or capture fails
    """
    try:
        # Try to find the actual djay Pro window
        window_bounds = _get_djay_window_bounds_via_applescript()
        
        if not window_bounds:
            raise DjayProWindowNotFoundError(
                "djay Pro window not found. Please ensure djay Pro is running. "
                "The application will only capture the djay Pro window, not the entire screen."
            )
        
        x, y, width, height = window_bounds
        
        # Try to get window ID for direct capture (bypasses windows in front)
        window_id = _get_djay_window_id_via_cgwindow()
        
        # Try direct window capture first (bypasses windows in front)
        # Note: CGWindow capture sometimes returns transparent/empty images
        # so we'll verify the capture has content before using it
        if window_id:
            direct_capture = _capture_window_via_cgwindow(window_id, window_bounds)
            if direct_capture:
                # Verify the image has actual content (not just white/transparent)
                # Check a few sample pixels
                sample_pixels = [direct_capture.getpixel((i, min(50, direct_capture.height-1))) 
                                for i in range(0, min(100, direct_capture.width), 20)]
                # If all pixels are white, the capture likely failed
                if not all(p == (255, 255, 255) for p in sample_pixels):
                    logger.info("Captured full window content directly (bypassed windows in front)")
                    return direct_capture
                else:
                    logger.debug("Direct window capture returned empty/white image, falling back to mss")
            else:
                logger.debug("Direct window capture failed, falling back to mss")
        
        # Fallback to mss (will capture what's visible, including windows in front)
        with mss.mss() as sct:
            # Get all monitors
            if len(sct.monitors) < 2:
                raise DjayProWindowNotFoundError("No monitors found")
            
            # Find which monitor contains the window
            monitor = _find_monitor_for_window(window_bounds, sct.monitors)
            
            if not monitor:
                raise DjayProWindowNotFoundError("Could not determine which monitor contains the window")
            
            # We found the window, capture the full window
            x, y, width, height = window_bounds
            
            # Validate window bounds are reasonable (not the whole screen)
            if width <= 0 or height <= 0:
                raise DjayProWindowNotFoundError(f"Invalid window size: {width}x{height}")
            
            # Validate bounds are not suspiciously large (likely whole screen)
            # Typical djay Pro window is 800-2000px wide, 600-1200px tall
            if width > 3000 or height > 2000:
                raise DjayProWindowNotFoundError(
                    f"Window bounds {width}x{height} are too large - likely capturing whole screen! "
                    f"Expected djay Pro window to be <3000x2000. Please check window bounds detection."
                )
            
            # Check if bounds match common screen dimensions (suspicious)
            common_screen_widths = [1920, 2560, 3840, 5120, 1440, 1680, 2880, 3440]
            common_screen_heights = [1080, 1440, 2160, 2880, 900, 1050, 1800]
            if width in common_screen_widths and height in common_screen_heights:
                raise DjayProWindowNotFoundError(
                    f"Window bounds {width}x{height} exactly match screen dimensions - "
                    f"this is likely wrong! Expected djay Pro window bounds, not screen bounds."
                )
            
            # Capture the full djay Pro window
            # Ensure we're using absolute screen coordinates (mss requirement)
            # The window bounds from AppleScript are already in absolute screen coordinates
            region = {
                "top": y,
                "left": x,
                "width": width,
                "height": height
            }
            
            # Validate region is within reasonable bounds
            if region["width"] > 5000 or region["height"] > 5000:
                raise DjayProWindowNotFoundError(f"Region too large (likely wrong): {region['width']}x{region['height']}")
            
            logger.info(f"Capturing full djay Pro window: x={x}, y={y}, width={width}, height={height}")
            logger.info(f"Capture region: top={region['top']}, left={region['left']}, width={region['width']}, height={region['height']}")
            logger.info(f"Expected image size: {region['width']}x{region['height']} pixels")
            
            screenshot = sct.grab(region)
            
            if screenshot is None:
                raise DjayProWindowNotFoundError("Failed to capture window region")
            
            # Verify captured size matches expected
            if screenshot.width != region["width"] or screenshot.height != region["height"]:
                logger.warning(f"Captured size {screenshot.width}x{screenshot.height} doesn't match expected {region['width']}x{region['height']}")
            
            # Convert to PIL Image
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            
            # Ensure we only have the exact window size (crop if needed)
            if img.size[0] != width or img.size[1] != height:
                logger.warning(f"Cropping image from {img.size} to exact window size {width}x{height}")
                img = img.crop((0, 0, min(width, img.size[0]), min(height, img.size[1])))
            
            logger.info(f"Successfully captured full djay Pro window: {img.size[0]}x{img.size[1]} pixels")
            return img
            
    except DjayProWindowNotFoundError:
        raise
    except Exception as e:
        logger.error(f"Error capturing djay Pro window: {e}", exc_info=True)
        raise DjayProWindowNotFoundError(f"Could not capture djay Pro window: {e}")

