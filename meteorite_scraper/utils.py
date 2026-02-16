import hashlib
import json
import logging
from pathlib import Path
from PIL import Image
import io
from config import IMAGES_DIR, METADATA_DIR, IMAGE_CONFIG

logger = logging.getLogger(__name__)

def generate_filename(url, meteorite_name=None, extension=None):
    """Generate a unique filename based on URL hash"""
    url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    
    if meteorite_name:
        # Clean meteorite name for filename
        safe_name = "".join(c for c in meteorite_name if c.isalnum() or c in (' ', '-', '_')).strip()
        safe_name = safe_name.replace(' ', '_')[:50]  # Limit length
        filename = f"{safe_name}_{url_hash}"
    else:
        filename = f"meteorite_{url_hash}"
    
    if extension:
        filename = f"{filename}.{extension}"
    
    return filename

def save_metadata_json(image_id, metadata, filename):
    """Save metadata as JSON sidecar file"""
    json_path = METADATA_DIR / f"{Path(filename).stem}.json"
    
    metadata_full = {
        'image_id': image_id,
        **metadata
    }
    
    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(metadata_full, f, indent=2, default=str)
        logger.debug(f"Saved metadata JSON: {json_path}")
    except Exception as e:
        logger.error(f"Error saving metadata JSON: {e}")

def validate_image(image_data):
    """Validate image data and return dimensions"""
    try:
        img = Image.open(io.BytesIO(image_data))
        width, height = img.size
        
        # Check minimum dimensions
        if width < IMAGE_CONFIG['min_width'] or height < IMAGE_CONFIG['min_height']:
            logger.warning(f"Image too small: {width}x{height}")
            return None
        
        # Check file size
        size_mb = len(image_data) / (1024 * 1024)
        if size_mb > IMAGE_CONFIG['max_file_size_mb']:
            logger.warning(f"Image too large: {size_mb:.2f}MB")
            return None
        
        return {
            'width': width,
            'height': height,
            'format': img.format.lower() if img.format else 'unknown',
            'size_bytes': len(image_data)
        }
    
    except Exception as e:
        logger.error(f"Error validating image: {e}")
        return None

def parse_classification(classification_string):
    """Parse meteorite classification string into components"""
    if not classification_string:
        return {'primary_type': None, 'secondary_type': None, 'detailed': None}
    
    classification = classification_string.lower().strip()
    
    # Determine primary type
    primary_type = None
    if 'iron' in classification and 'stony' not in classification:
        primary_type = 'iron'
    elif any(word in classification for word in ['chondrite', 'achondrite', 'eucrite', 'howardite', 'diogenite']):
        primary_type = 'stony'
    elif any(word in classification for word in ['pallasite', 'mesosiderite']):
        primary_type = 'stony-iron'
    
    # Determine secondary type
    secondary_type = None
    if 'chondrite' in classification:
        if 'carbonaceous' in classification or classification.startswith('c'):
            secondary_type = 'carbonaceous_chondrite'
        elif 'enstatite' in classification or classification.startswith('e'):
            secondary_type = 'enstatite_chondrite'
        elif 'ordinary' in classification or any(classification.startswith(x) for x in ['h', 'l', 'll']):
            secondary_type = 'ordinary_chondrite'
        else:
            secondary_type = 'chondrite'
    elif 'achondrite' in classification:
        secondary_type = 'achondrite'
    elif 'iron' in classification:
        secondary_type = 'iron'
    elif 'pallasite' in classification:
        secondary_type = 'pallasite'
    elif 'mesosiderite' in classification:
        secondary_type = 'mesosiderite'
    
    return {
        'primary_type': primary_type,
        'secondary_type': secondary_type,
        'detailed': classification_string
    }

def setup_logging(log_file='scraper.log'):
    """Setup logging configuration"""
    from config import LOGS_DIR
    
    log_path = LOGS_DIR / log_file
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_path),
            logging.StreamHandler()
        ]
    )
    