"""
Musical Key Translator
Translates Camelot wheel keys (1A, 1B, etc.) to musical key characteristics and emotions.
Based on the Camelot wheel system and traditional musical key characteristics.
"""
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

# Camelot Wheel Key to Musical Key Characteristics
# Format: "CamelotKey": ["characteristic1", "characteristic2", ...]
CAMELOT_KEY_CHARACTERISTICS = {
    # A keys (Major keys)
    "1A": ["innocent", "pure", "simple", "happy", "cheerful", "bright"],
    "2A": ["triumphant", "victorious", "joyful", "energetic", "uplifting"],
    "3A": ["warm", "tender", "gentle", "peaceful", "calm"],
    "4A": ["optimistic", "hopeful", "bright", "energetic", "positive"],
    "5A": ["majestic", "grand", "powerful", "confident", "bold"],
    "6A": ["pastoral", "serene", "peaceful", "gentle", "calm"],
    "7A": ["bright", "cheerful", "energetic", "uplifting", "happy"],
    "8A": ["heroic", "triumphant", "powerful", "confident", "bold"],
    "9A": ["warm", "tender", "gentle", "peaceful", "serene"],
    "10A": ["bright", "cheerful", "energetic", "uplifting", "optimistic"],
    "11A": ["majestic", "grand", "powerful", "confident", "bold"],
    "12A": ["tender", "gentle", "peaceful", "calm", "serene"],
    
    # B keys (Minor keys)
    "1B": ["sad", "melancholic", "tender", "introspective", "emotional"],
    "2B": ["mysterious", "dark", "brooding", "intense", "dramatic"],
    "3B": ["sad", "melancholic", "tender", "emotional", "introspective"],
    "4B": ["mysterious", "dark", "brooding", "intense", "dramatic"],
    "5B": ["sad", "melancholic", "tender", "emotional", "introspective"],
    "6B": ["mysterious", "dark", "brooding", "intense", "dramatic"],
    "7B": ["sad", "melancholic", "tender", "emotional", "introspective"],
    "8B": ["mysterious", "dark", "brooding", "intense", "dramatic"],
    "9B": ["sad", "melancholic", "tender", "emotional", "introspective"],
    "10B": ["mysterious", "dark", "brooding", "intense", "dramatic"],
    "11B": ["sad", "melancholic", "tender", "emotional", "introspective"],
    "12B": ["mysterious", "dark", "brooding", "intense", "dramatic"],
}

# Traditional musical key characteristics (for reference, if we need to convert from standard notation)
TRADITIONAL_KEY_CHARACTERISTICS = {
    "C Major": ["innocent", "pure", "simple", "happy"],
    "C Minor": ["sad", "melancholic", "tender"],
    "D Major": ["triumphant", "victorious", "joyful"],
    "D Minor": ["mysterious", "dark", "brooding"],
    "E Major": ["warm", "tender", "gentle"],
    "E Minor": ["sad", "melancholic", "tender"],
    "F Major": ["optimistic", "hopeful", "bright"],
    "F Minor": ["mysterious", "dark", "brooding"],
    "G Major": ["majestic", "grand", "powerful"],
    "G Minor": ["sad", "melancholic", "tender"],
    "A Major": ["bright", "cheerful", "energetic"],
    "A Minor": ["tender", "gentle", "peaceful"],
    "B Major": ["heroic", "triumphant", "powerful"],
    "B Minor": ["mysterious", "dark", "brooding"],
}


def translate_key_to_characteristics(key: Optional[str]) -> List[str]:
    """
    Translate a Camelot wheel key (e.g., "1A", "2B") to musical characteristics.
    
    Args:
        key: Camelot wheel key string (e.g., "1A", "2B", "12A")
        
    Returns:
        List of characteristic keywords (e.g., ["triumphant", "victorious", "joyful"])
        Returns empty list if key is None or not found
    """
    if not key:
        return []
    
    # Normalize key (remove whitespace, uppercase)
    key = str(key).strip().upper()
    
    # Check if it's a Camelot wheel key (format: number + A or B)
    if key in CAMELOT_KEY_CHARACTERISTICS:
        characteristics = CAMELOT_KEY_CHARACTERISTICS[key]
        logger.debug(f"Translated key '{key}' to characteristics: {characteristics}")
        return characteristics
    
    # If not found, log warning and return empty list
    logger.warning(f"Unknown key format: '{key}'. Expected Camelot wheel format (e.g., '1A', '2B')")
    return []


def get_key_characteristics(key: Optional[str]) -> List[str]:
    """
    Alias for translate_key_to_characteristics for convenience.
    """
    return translate_key_to_characteristics(key)

