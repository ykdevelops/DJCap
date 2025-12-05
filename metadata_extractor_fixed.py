def _extract_deck_metadata_regions(deck_region: np.ndarray, deck_name: str, coords: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Extract metadata from a deck using color-based detection for title/artist/BPM,
    falling back to coordinate-based if color detection fails.
    
    Args:
        deck_region: numpy array image for one deck (left or right half)
        deck_name: Name of the deck for logging ("deck1" or "deck2")
        coords: Optional coordinates dictionary from region_coordinates.json
        
    Returns:
        Dictionary with title, artist, bpm, key
    """
    deck_height, deck_width = deck_region.shape[:2]
    
    # Try color-based detection first
    color_regions = _detect_text_regions_by_color(deck_region)
    
    # Use color-based regions if detected, otherwise fall back to coordinate-based
    use_color_detection = color_regions['title'] is not None and color_regions['artist'] is not None
    
    if use_color_detection:
        logger.debug(f"Using color-based detection for {deck_name}")
        # Extract regions using color detection
        title_bbox = color_regions['title']
        artist_bbox = color_regions['artist']
        bpm_bbox = color_regions['bpm']
        
        # Extract title region
        if title_bbox:
            title_x_start, title_y_start, title_x_end, title_y_end = title_bbox
            title_x_start = max(0, title_x_start - REGION_PADDING)
            title_x_end = min(deck_width, title_x_end + REGION_PADDING)
            title_y_start = max(0, title_y_start - REGION_PADDING)
            title_y_end = min(deck_height, title_y_end + REGION_PADDING)
        else:
            title_x_start = title_y_start = title_x_end = title_y_end = 0
        
        # Extract artist region
        if artist_bbox:
            artist_x_start, artist_y_start, artist_x_end, artist_y_end = artist_bbox
            artist_x_start = max(0, artist_x_start - REGION_PADDING)
            artist_x_end = min(deck_width, artist_x_end + REGION_PADDING)
            artist_y_start = max(0, artist_y_start - REGION_PADDING)
            artist_y_end = min(deck_height, artist_y_end + REGION_PADDING)
        else:
            artist_x_start = artist_y_start = artist_x_end = artist_y_end = 0
        
        # Extract BPM region
        if bpm_bbox:
            bpm_x_start, bpm_y_start, bpm_x_end, bpm_y_end = bpm_bbox
            bpm_x_start = max(0, bpm_x_start - REGION_PADDING)
            bpm_x_end = min(deck_width, bpm_x_end + REGION_PADDING)
            bpm_y_start = max(0, bpm_y_start - REGION_PADDING)
            bpm_y_end = min(deck_height, bpm_y_end + REGION_PADDING)
        else:
            bpm_x_start = bpm_y_start = bpm_x_end = bpm_y_end = 0
        
        # For key, use coordinate-based (it's usually in a fixed position)
        if coords:
            deck_regions = coords.get(f'{deck_name}_regions', {})
            key_pct = deck_regions.get('key', {}).get('percentages', {})
            key_x_start = int(deck_width * key_pct.get('x_start', 0.9114))
            key_x_end = int(deck_width * key_pct.get('x_end', 0.9844))
            key_y_start = int(deck_height * key_pct.get('y_start', 0.0541))
            key_y_end = int(deck_height * key_pct.get('y_end', 0.4775))
        else:
            if deck_name == "deck1":
                key_x_start = int(deck_width * 0.9114)
                key_x_end = int(deck_width * 0.9844)
                key_y_start = int(deck_height * 0.0541)
                key_y_end = int(deck_height * 0.4775)
            else:
                key_x_start = int(deck_width * 0.8113)
                key_x_end = int(deck_width * 0.8711)
                key_y_start = int(deck_height * 0.1053)
                key_y_end = int(deck_height * 0.4474)
    else:
        # Fall back to coordinate-based detection
        logger.debug(f"Using coordinate-based detection for {deck_name}")
        if coords:
            deck_regions = coords.get(f'{deck_name}_regions', {})
            if deck_regions:
                # Use percentages from coordinates file
                title_pct = deck_regions.get('title', {}).get('percentages', {})
                title_x_start = int(deck_width * title_pct.get('x_start', 0.1178))
                title_x_end = int(deck_width * title_pct.get('x_end', 0.8081))
                title_y_start = int(deck_height * title_pct.get('y_start', 0.0360))
                title_y_end = int(deck_height * title_pct.get('y_end', 0.3243))
                
                artist_pct = deck_regions.get('artist', {}).get('percentages', {})
                artist_x_start = int(deck_width * artist_pct.get('x_start', 0.1157))
                artist_x_end = int(deck_width * artist_pct.get('x_end', 0.2440))
                artist_y_start = int(deck_height * artist_pct.get('y_start', 0.3423))
                artist_y_end = int(deck_height * artist_pct.get('y_end', 0.5135))
                
                bpm_pct = deck_regions.get('bpm', {}).get('percentages', {})
                bpm_x_start = int(deck_width * bpm_pct.get('x_start', 0.2544))
                bpm_x_end = int(deck_width * bpm_pct.get('x_end', 0.3045))
                bpm_y_start = int(deck_height * bpm_pct.get('y_start', 0.3333))
                bpm_y_end = int(deck_height * bpm_pct.get('y_end', 0.5045))
                
                key_pct = deck_regions.get('key', {}).get('percentages', {})
                key_x_start = int(deck_width * key_pct.get('x_start', 0.9114))
                key_x_end = int(deck_width * key_pct.get('x_end', 0.9844))
                key_y_start = int(deck_height * key_pct.get('y_start', 0.0541))
                key_y_end = int(deck_height * key_pct.get('y_end', 0.4775))
            else:
                # Fallback to defaults
                if deck_name == "deck1":
                    title_x_start, title_x_end = int(deck_width * 0.1178), int(deck_width * 0.8081)
                    title_y_start, title_y_end = int(deck_height * 0.0360), int(deck_height * 0.3243)
                    artist_x_start, artist_x_end = int(deck_width * 0.1157), int(deck_width * 0.2440)
                    artist_y_start, artist_y_end = int(deck_height * 0.3423), int(deck_height * 0.5135)
                    bpm_x_start, bpm_x_end = int(deck_width * 0.2544), int(deck_width * 0.3045)
                    bpm_y_start, bpm_y_end = int(deck_height * 0.3333), int(deck_height * 0.5045)
                    key_x_start, key_x_end = int(deck_width * 0.9114), int(deck_width * 0.9844)
                    key_y_start, key_y_end = int(deck_height * 0.0541), int(deck_height * 0.4775)
                else:
                    title_x_start, title_x_end = int(deck_width * 0.0063), int(deck_width * 0.6939)
                    title_y_start, title_y_end = int(deck_height * 0.0351), int(deck_height * 0.3333)
                    artist_x_start, artist_x_end = int(deck_width * 0.0073), int(deck_width * 0.1719)
                    artist_y_start, artist_y_end = int(deck_height * 0.3509), int(deck_height * 0.5263)
                    bpm_x_start, bpm_x_end = int(deck_width * 0.1771), int(deck_width * 0.2275)
                    bpm_y_start, bpm_y_end = int(deck_height * 0.3333), int(deck_height * 0.5175)
                    key_x_start, key_x_end = int(deck_width * 0.8113), int(deck_width * 0.8711)
                    key_y_start, key_y_end = int(deck_height * 0.1053), int(deck_height * 0.4474)
        else:
            # Use default coordinates
            if deck_name == "deck1":
                title_x_start, title_x_end = int(deck_width * 0.1178), int(deck_width * 0.8081)
                title_y_start, title_y_end = int(deck_height * 0.0360), int(deck_height * 0.3243)
                artist_x_start, artist_x_end = int(deck_width * 0.1157), int(deck_width * 0.2440)
                artist_y_start, artist_y_end = int(deck_height * 0.3423), int(deck_height * 0.5135)
                bpm_x_start, bpm_x_end = int(deck_width * 0.2544), int(deck_width * 0.3045)
                bpm_y_start, bpm_y_end = int(deck_height * 0.3333), int(deck_height * 0.5045)
                key_x_start, key_x_end = int(deck_width * 0.9114), int(deck_width * 0.9844)
                key_y_start, key_y_end = int(deck_height * 0.0541), int(deck_height * 0.4775)
            else:
                title_x_start, title_x_end = int(deck_width * 0.0063), int(deck_width * 0.6939)
                title_y_start, title_y_end = int(deck_height * 0.0351), int(deck_height * 0.3333)
                artist_x_start, artist_x_end = int(deck_width * 0.0073), int(deck_width * 0.1719)
                artist_y_start, artist_y_end = int(deck_height * 0.3509), int(deck_height * 0.5263)
                bpm_x_start, bpm_x_end = int(deck_width * 0.1771), int(deck_width * 0.2275)
                bpm_y_start, bpm_y_end = int(deck_height * 0.3333), int(deck_height * 0.5175)
                key_x_start, key_x_end = int(deck_width * 0.8113), int(deck_width * 0.8711)
                key_y_start, key_y_end = int(deck_height * 0.1053), int(deck_height * 0.4474)
    
    # Expand regions with padding for better OCR accuracy
    title_x_start = max(0, title_x_start - REGION_PADDING)
    title_x_end = min(deck_width, title_x_end + REGION_PADDING)
    title_y_start = max(0, title_y_start - REGION_PADDING)
    title_y_end = min(deck_height, title_y_end + REGION_PADDING)
    
    artist_x_start = max(0, artist_x_start - REGION_PADDING)
    artist_x_end = min(deck_width, artist_x_end + REGION_PADDING)
    artist_y_start = max(0, artist_y_start - REGION_PADDING)
    artist_y_end = min(deck_height, artist_y_end + REGION_PADDING)
    
    key_x_start = max(0, key_x_start - REGION_PADDING)
    key_x_end = min(deck_width, key_x_end + REGION_PADDING)
    key_y_start = max(0, key_y_start - REGION_PADDING)
    key_y_end = min(deck_height, key_y_end + REGION_PADDING)
    
    bpm_x_start = max(0, bpm_x_start - REGION_PADDING)
    bpm_x_end = min(deck_width, bpm_x_end + REGION_PADDING)
    bpm_y_start = max(0, bpm_y_start - REGION_PADDING)
    bpm_y_end = min(deck_height, bpm_y_end + REGION_PADDING)
    
    # Extract regions
    title_region = deck_region[title_y_start:title_y_end, title_x_start:title_x_end]
    artist_region = deck_region[artist_y_start:artist_y_end, artist_x_start:artist_x_end]
    bpm_region = deck_region[bpm_y_start:bpm_y_end, bpm_x_start:bpm_x_end]
    key_region = deck_region[key_y_start:key_y_end, key_x_start:key_x_end]
    
    # Convert numpy arrays to PIL Images for ocrmac
    title_image = Image.fromarray(title_region)
    artist_image = Image.fromarray(artist_region)
    bpm_image = Image.fromarray(bpm_region)
    key_image = Image.fromarray(key_region)
    
    # Extract text from each region using ocrmac
    title = _extract_text_with_ocrmac(title_image, f"{deck_name}_title")
    artist = _extract_text_with_ocrmac(artist_image, f"{deck_name}_artist")
    
    # Extract BPM from BPM region
    bpm_text = _extract_text_with_ocrmac(bpm_image, f"{deck_name}_bpm")
    bpm = _extract_bpm_from_text(bpm_text) if bpm_text else None
    
    # Extract key from key region
    key_text = _extract_text_with_ocrmac(key_image, f"{deck_name}_key")
    key = _extract_key_from_text(key_text) if key_text else None
    
    metadata = {
        "deck": deck_name,
        "title": title,
        "artist": artist,
        "bpm": bpm,
        "key": key
    }
    
    logger.debug(f"Region-based extraction for {deck_name}: title={title}, artist={artist}, bpm={bpm}, key={key}")
    
    return metadata

