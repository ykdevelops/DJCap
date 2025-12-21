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
    # Prefer repo root `.env` (per README), but keep `src/.env` as a fallback.
    # This makes local dev less surprising and preserves backwards compatibility.
    repo_root_env = Path(__file__).resolve().parent.parent / ".env"
    src_env = Path(__file__).resolve().parent / ".env"

    if repo_root_env.exists():
        load_dotenv(repo_root_env)
    elif src_env.exists():
        load_dotenv(src_env)
except ImportError:
    # python-dotenv not installed, try manual .env parsing as fallback
    repo_root_env = Path(__file__).resolve().parent.parent / ".env"
    src_env = Path(__file__).resolve().parent / ".env"
    
    env_file = repo_root_env if repo_root_env.exists() else (src_env if src_env.exists() else None)
    if env_file:
        try:
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key and value:
                            os.environ[key] = value
        except Exception:
            pass  # If manual parsing fails, continue without .env

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

