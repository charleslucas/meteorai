import requests
from bs4 import BeautifulSoup
import time
import logging
from pathlib import Path
from tqdm import tqdm
from config import SCRAPE_CONFIG, IMAGES_DIR
from database import DatabaseManager
from utils import (
    generate_filename, save_metadata_json, 
    validate_image, parse_classification
)

logger = logging.getLogger(__name__)

class MeteoriteImageScraper:
    """Main scraper class that coordinates scraping from multiple sources"""
    
    #def __init__(self):
    #    self.db = DatabaseManager()
    #    self.session = requests.Session()
    #    self.session.headers.update({
    #        'User-Agent': SCRAPE_CONFIG['user_agent']
    #    })
    #    self.stats = {
    #        'images_found': 0,
    #        'images_downloaded': 0,
    #        'images_skipped': 0,
    #        'errors': 0
    #    }

    def __init__(self):
        self.db = DatabaseManager()
        self.session = requests.Session()

        # Use all the headers from config
        self.session.headers.update(SCRAPE_CONFIG.get('headers', {
            'User-Agent': SCRAPE_CONFIG['user_agent']
        }))

        self.stats = {
            'images_found': 0,
            'images_downloaded': 0,
            'images_skipped': 0,
            'errors': 0
        }        
    
    def download_image(self, url, max_retries=None):
        """Download image from URL with retry logic"""
        if max_retries is None:
            max_retries = SCRAPE_CONFIG['max_retries']
        
        for attempt in range(max_retries):
            try:
                response = self.session.get(
                    url,
                    timeout=SCRAPE_CONFIG['request_timeout'],
                    stream=True
                )
                response.raise_for_status()
                
                # Download in chunks
                image_data = b''
                for chunk in response.iter_content(chunk_size=SCRAPE_CONFIG['chunk_size']):
                    if chunk:
                        image_data += chunk
                
                return image_data
            
            except requests.RequestException as e:
                logger.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    logger.error(f"Failed to download {url} after {max_retries} attempts")
                    return None
    
    def process_image(self, image_url, metadata):
        """Download and process a single image"""
        try:
            # Check if already scraped
            if self.db.url_exists(image_url):
                logger.info(f"Image already exists: {image_url}")

                # If we have a photo_page_url in metadata, update the existing record
                photo_page_url = metadata.get('photo_page_url')
                if photo_page_url:
                    updated = self.db.update_photo_page_url(image_url, photo_page_url)
                    if updated:
                        logger.info(f"  → Linked photo page URL to existing image")

                self.stats['images_skipped'] += 1
                return None
            
            # Download image
            logger.info(f"Downloading: {image_url}")
            image_data = self.download_image(image_url)
            
            if not image_data:
                self.stats['errors'] += 1
                return None
            
            # Validate image
            image_info = validate_image(image_data)
            if not image_info:
                logger.warning(f"Image validation failed: {image_url}")
                self.stats['errors'] += 1
                return None
            
            # Generate filename
            extension = image_info['format']
            if extension == 'jpeg':
                extension = 'jpg'
            
            filename = generate_filename(
                image_url,
                metadata.get('meteorite_name'),
                extension
            )
            
            # Save image
            filepath = IMAGES_DIR / filename
            with open(filepath, 'wb') as f:
                f.write(image_data)
            
            logger.info(f"Saved image: {filepath}")
            
            # Parse classification
            classification = parse_classification(metadata.get('classification', ''))
            
            # Prepare database record
            db_data = {
                'meteorite_name': metadata.get('meteorite_name'),
                'original_filename': image_url.split('/')[-1],
                'stored_filename': filename,
                'source_url': image_url,
                'page_url': metadata.get('page_url'),
                'photo_page_url': metadata.get('photo_page_url'),
                'file_format': extension,
                'file_size_bytes': image_info['size_bytes'],
                'width_px': image_info['width'],
                'height_px': image_info['height'],
                'primary_type': classification['primary_type'],
                'secondary_type': classification['secondary_type'],
                'detailed_classification': classification['detailed'],
                'mass_grams': metadata.get('mass_grams'),
                'fall_or_find': metadata.get('fall_or_find'),
                'discovery_date': metadata.get('discovery_date'),
                'discovery_location': metadata.get('discovery_location'),
                'discovery_latitude': metadata.get('discovery_latitude'),
                'discovery_longitude': metadata.get('discovery_longitude'),
                'terrain_type': metadata.get('terrain_type'),
                'image_context': metadata.get('image_context', 'unknown'),
                'viewing_angle': metadata.get('viewing_angle'),
                'background_type': metadata.get('background_type'),
                'lighting_type': metadata.get('lighting_type'),
                'license': metadata.get('license'),
                'photographer': metadata.get('photographer'),
                'data_confidence': metadata.get('data_confidence', 'medium'),
                'needs_review': metadata.get('needs_review', True),
                'notes': metadata.get('notes', '')
            }
            
            # Insert into database
            image_id = self.db.insert_meteorite(db_data)
            
            # Save JSON metadata
            save_metadata_json(image_id, metadata, filename)
            
            self.stats['images_downloaded'] += 1
            
            # Rate limiting
            time.sleep(SCRAPE_CONFIG['rate_limit_delay'])
            
            return image_id
        
        except Exception as e:
            logger.error(f"Error processing image {image_url}: {e}")
            self.stats['errors'] += 1
            return None
    
    def scrape_source(self, source_scraper, source_name):
        """Scrape from a specific source"""
        logger.info(f"Starting scrape from: {source_name}")
        
        try:
            # Get images from source
            images = source_scraper.get_images()
            self.stats['images_found'] = len(images)
            
            logger.info(f"Found {len(images)} images from {source_name}")
            
            # Process each image
            for image_data in tqdm(images, desc=f"Processing {source_name}"):
                self.process_image(image_data['url'], image_data['metadata'])
            
            # Log session
            self.db.log_scrape_session(
                source_name=source_name,
                images_found=self.stats['images_found'],
                images_downloaded=self.stats['images_downloaded'],
                errors=self.stats['errors'],
                status='completed'
            )
            
            logger.info(f"Completed scrape from {source_name}")
            logger.info(f"Stats: {self.stats}")
            
        except Exception as e:
            logger.error(f"Error scraping {source_name}: {e}")
            self.db.log_scrape_session(
                source_name=source_name,
                images_found=self.stats['images_found'],
                images_downloaded=self.stats['images_downloaded'],
                errors=self.stats['errors'],
                status='failed',
                notes=str(e)
            )
    
    def print_statistics(self):
        """Print database statistics"""
        stats = self.db.get_statistics()
        
        print("\n" + "="*50)
        print("DATABASE STATISTICS")
        print("="*50)
        print(f"Total images: {stats['total_images']}")
        print(f"\nBy type:")
        for type_name, count in stats['by_type'].items():
            print(f"  {type_name}: {count}")
        print(f"\nBy context:")
        for context, count in stats['by_context'].items():
            print(f"  {context}: {count}")
        print(f"\nNeeds review: {stats['needs_review']}")
        print("="*50 + "\n")
        