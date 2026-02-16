import requests
from bs4 import BeautifulSoup
import logging
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

class NASACuratorScraper:
    """Scraper for NASA's meteorite collection pages"""
    
    BASE_URL = "https://curator.jsc.nasa.gov/"
    
    def __init__(self, session=None):
        self.session = session or requests.Session()
        self.session.headers.update({
            'User-Agent': 'MeteoriteResearchBot/1.0 (Educational Research)'
        })
    
    def scrape_antarctic_collection(self):
        """Scrape NASA's Antarctic meteorite collection"""
        url = f"{self.BASE_URL}antmet/index.cfm"
        
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            images = []
            
            # Look for gallery or image links
            for img in soup.find_all('img'):
                src = img.get('src', '')
                if src and 'meteorite' in src.lower():
                    img_url = urljoin(url, src)
                    
                    # Try to extract metadata from surrounding text
                    parent = img.find_parent()
                    caption = parent.get_text(strip=True) if parent else ''
                    
                    images.append({
                        'url': img_url,
                        'metadata': {
                            'meteorite_name': caption[:100] if caption else 'Unknown',
                            'source': 'nasa_antarctic',
                            'image_context': 'museum_display',
                            'discovery_location': 'Antarctica',
                            'terrain_type': 'ice_field',
                            'page_url': url,
                            'notes': caption
                        }
                    })
            
            return images
        
        except Exception as e:
            logger.error(f"Error scraping NASA Antarctic collection: {e}")
            return []
    
    def get_images(self):
        """Get all available NASA images"""
        all_images = []
        
        logger.info("Scraping NASA Antarctic meteorite collection")
        all_images.extend(self.scrape_antarctic_collection())
        
        return all_images