"""
Configuration file for DjCap API credentials.
Create a .env file in the root directory with your credentials:
LASTFM_API_KEY=your_lastfm_key
GIPHY_API_KEY=your_giphy_key
"""
import os
from pathlib import Path

# Try to load from .env file
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / '.env'
    load_dotenv(env_path)
except ImportError:
    # python-dotenv not installed, will use environment variables only
    pass

# Last.fm API credentials
LASTFM_API_KEY = os.getenv('LASTFM_API_KEY', '')

# Giphy API credentials
GIPHY_API_KEY = os.getenv('GIPHY_API_KEY', '')

# If keys are empty, try to import from AudioApis config as fallback
if not LASTFM_API_KEY or not GIPHY_API_KEY:
    try:
        import sys
        audioapis_path = '/Users/youssefkhalil/AudioApis'
        if os.path.exists(audioapis_path):
            sys.path.insert(0, audioapis_path)
            try:
                from config import LASTFM_API_KEY as AUDIOAPIS_LASTFM_KEY, GIPHY_API_KEY as AUDIOAPIS_GIPHY_KEY
                if not LASTFM_API_KEY and AUDIOAPIS_LASTFM_KEY:
                    LASTFM_API_KEY = AUDIOAPIS_LASTFM_KEY
                if not GIPHY_API_KEY and AUDIOAPIS_GIPHY_KEY:
                    GIPHY_API_KEY = AUDIOAPIS_GIPHY_KEY
            except ImportError:
                pass
    except Exception:
        pass

