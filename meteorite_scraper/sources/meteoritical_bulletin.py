import requests
from bs4 import BeautifulSoup
import logging
import time
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

class MeteoriticalBulletinScraper:
    """Scraper for the Meteoritical Bulletin Database"""
    
    BASE_URL = "https://www.lpi.usra.edu/meteor/"
    
    def __init__(self, session=None):
        self.session = session or requests.Session()
        self.session.headers.update({
            'User-Agent': 'MeteoriteResearchBot/1.0 (Educational Research)'
        })
    
    def search_meteorite(self, name):
        """Search for a specific meteorite by name"""
        search_url = f"{self.BASE_URL}metbull.php"
        params = {'sea': name}
        
        try:
            response = self.session.get(search_url, params=params, timeout=30)
            response.raise_for_status()
            return self.parse_meteorite_page(response.content, response.url)
        except Exception as e:
            logger.error(f"Error searching for {name}: {e}")
            return []
    
    def parse_meteorite_page(self, html_content, page_url):
        """Parse a meteorite detail page"""
        soup = BeautifulSoup(html_content, 'html.parser')
        
        images = []
        metadata = {'page_url': page_url}
        
        # Extract meteorite name
        title = soup.find('h1')
        if title:
            metadata['meteorite_name'] = title.text.strip()
        
        # Extract from table
        for row in soup.find_all('tr'):
            cells = row.find_all('td')
            if len(cells) >= 2:
                key = cells[0].text.strip().rstrip(':').lower()
                value = cells[1].text.strip()
                
                if key == 'classification':
                    metadata['classification'] = value
                elif key == 'mass':
                    try:
                        # Extract numeric value (remove ' g' or 'kg')
                        mass_str = value.split()[0].replace(',', '')
                        metadata['mass_grams'] = float(mass_str)
                    except:
                        pass
                elif key == 'found' or key == 'fell':
                    metadata['fall_or_find'] = key
                    metadata['discovery_date'] = value
                elif key == 'location':
                    metadata['discovery_location'] = value
        
        # Find images
        for img in soup.find_all('img'):
            src = img.get('src', '')
            if src and not src.startswith('data:'):
                img_url = urljoin(page_url, src)
                
                # Skip small icons/logos
                if any(skip in src.lower() for skip in ['icon', 'logo', 'button']):
                    continue
                
                images.append({
                    'url': img_url,
                    'metadata': {
                        **metadata,
                        'alt_text': img.get('alt', ''),
                        'image_context': 'database_photo',
                        'source': 'meteoritical_bulletin'
                    }
                })
        
        return images
    
    def get_images(self, meteorite_names=None):
        """Get images for a list of meteorite names"""
        if meteorite_names is None:
            # Default list of well-known meteorites
            meteorite_names = [
                'Allende', 'Murchison', 'Canyon Diablo', 'Willamette',
                'Hoba', 'Campo del Cielo', 'Sikhote-Alin', 'Chelyabinsk',
                'Fukang', 'Esquel', 'Gibeon', 'Seymchan'
            ]
        
        all_images = []
        for name in meteorite_names:
            logger.info(f"Searching Meteoritical Bulletin for: {name}")
            images = self.search_meteorite(name)
            all_images.extend(images)
            time.sleep(2)  # Be respectful
        
        return all_images
