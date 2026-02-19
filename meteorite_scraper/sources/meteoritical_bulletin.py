try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    USING_SELENIUM = True
except ImportError:
    USING_SELENIUM = False

from bs4 import BeautifulSoup
import logging
import time
import re
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

class MeteoriticalBulletinScraper:
    """Scraper for the Meteoritical Bulletin Database using Selenium"""

    BASE_URL = "https://www.lpi.usra.edu/meteor/"
    # Default listing URL for meteorites with photos
    LISTING_URL = "https://www.lpi.usra.edu/meteor/metbull.cfm?sfor=names&stype=contains&sea=*&country=All&categ=All&ants=no&falls=yes&nwas=no&phot=yes&map=ge&srt=name&page=0&lrec=1000&pnt=Normal+table&mblist=All&snew=0"

    def __init__(self, headless=True):
        """
        Initialize the scraper with Selenium.

        Args:
            headless: Run Chrome in headless mode (default True)
        """
        if not USING_SELENIUM:
            raise ImportError("Selenium is required. Install with: pip install selenium undetected-chromedriver")

        logger.info("Initializing Selenium with undetected-chromedriver...")

        # Create undetected Chrome driver
        # Note: undetected-chromedriver handles most anti-detection automatically
        options = uc.ChromeOptions()

        # WARNING: Headless mode is easier for Cloudflare to detect
        # For best results, use headless=False
        if headless:
            logger.warning("Running in headless mode - Cloudflare detection is more likely!")
            options.add_argument('--headless=new')

        # Basic options for stability
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')

        # Window size (helps with headless detection)
        options.add_argument('--window-size=1920,1080')

        # Let undetected-chromedriver handle the rest automatically
        self.driver = uc.Chrome(options=options, version_main=None, use_subprocess=True)
        self.driver.implicitly_wait(10)
        self._session_initialized = False
        logger.info("Selenium driver initialized successfully")

    def _initialize_session(self):
        """Visit the homepage to establish session and get cookies"""
        if self._session_initialized:
            return

        try:
            logger.info("Initializing session by visiting homepage...")
            self.driver.get(self.BASE_URL)
            time.sleep(2)  # Wait for page to load
            self._session_initialized = True
            logger.info("Session initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize session: {e}")

    def scrape_meteorite_listing(self, listing_url=None):
        """
        Scrape the meteorite listing page and extract detail page URLs.
        Returns a list of (name, url) tuples.
        """
        if listing_url is None:
            listing_url = self.LISTING_URL

        # Initialize session by visiting homepage first
        self._initialize_session()

        try:
            logger.info(f"Fetching meteorite listing from: {listing_url}")
            self.driver.get(listing_url)

            # Wait for Cloudflare challenge to complete
            logger.info("Waiting for Cloudflare challenge to complete...")
            max_wait = 60  # Maximum 60 seconds (Cloudflare can take a while)
            wait = WebDriverWait(self.driver, max_wait)

            # Give Cloudflare's JavaScript time to initialize
            time.sleep(5)

            try:
                # Wait until we see meteorite names (span.mname) which means the real page loaded
                wait.until(EC.presence_of_element_located((By.CLASS_NAME, "mname")))
                logger.info("Cloudflare challenge completed, page loaded successfully")
            except Exception as e:
                logger.warning("Timeout waiting for page content. Cloudflare may have blocked us.")
                logger.warning(f"Page title: {self.driver.title}")
                logger.warning(f"Error: {str(e)}")
                # Continue anyway to see what we got

            time.sleep(2)  # Additional wait for dynamic content

            logger.info(f"Page title: {self.driver.title}")

            # Debug: Print received HTML
            logger.info("=" * 80)
            logger.info("Received HTML:")
            logger.info("*************************************************")
            logger.info(self.driver.page_source)
            logger.info("*************************************************")
            logger.info("=" * 80)

            # Get page source and parse with BeautifulSoup
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            meteorite_links = []

            # Find all meteorite names - they're in <span class="mname"> tags
            for mname_span in soup.find_all('span', class_='mname'):
                link = mname_span.find('a')
                if link and link.get('href'):
                    meteorite_name = link.text.strip()
                    detail_url = urljoin(self.driver.current_url, link['href'])
                    meteorite_links.append((meteorite_name, detail_url))
                    logger.debug(f"Found meteorite: {meteorite_name} -> {detail_url}")

            logger.info(f"Found {len(meteorite_links)} meteorites in listing")
            return meteorite_links

        except Exception as e:
            logger.error(f"Error scraping meteorite listing: {e}")
            return []

    def parse_meteorite_page(self, html_content, page_url):
        """Parse a meteorite detail page and extract photos from the Photos section"""
        soup = BeautifulSoup(html_content, 'html.parser')

        images = []
        metadata = {'page_url': page_url}

        # Extract meteorite name
        title = soup.find('h1')
        if title:
            metadata['meteorite_name'] = title.text.strip()

        # Extract metadata from table
        for row in soup.find_all('tr'):
            cells = row.find_all('td')
            if len(cells) >= 2:
                key = cells[0].text.strip().rstrip(':').lower()
                value = cells[1].text.strip()

                # Check if we've entered the Photos section
                if key == 'photos' or 'photo' in key:
                    # Parse photos from this row
                    photos_data = self._parse_photos_cell(cells[1], page_url, metadata)
                    images.extend(photos_data)
                    continue

                # Extract other metadata
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

        return images

    def _parse_photos_cell(self, photos_cell, page_url, metadata):
        """
        Parse the Photos cell from a meteorite detail page.
        Extracts photo URLs and uploader information.
        """
        images = []

        # Look for all links in the photos cell
        for link in photos_cell.find_all('a'):
            href = link.get('href', '')

            # Check if this link points to an image
            if any(ext in href.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                img_url = urljoin(page_url, href)

                # Try to extract uploader information
                uploader = None
                link_text = link.text.strip()
                parent_text = link.parent.get_text() if link.parent else ''

                # Common patterns: "photo by John Doe", "(John Doe)", "© John Doe"
                if '(' in parent_text and ')' in parent_text:
                    match = re.search(r'\(([^)]+)\)', parent_text)
                    if match:
                        uploader = match.group(1).strip()

                # Also check for "by" pattern
                if not uploader and ' by ' in parent_text.lower():
                    match = re.search(r'by\s+([^,.\n]+)', parent_text, re.IGNORECASE)
                    if match:
                        uploader = match.group(1).strip()

                # Check if there's a sibling text node or nearby element with uploader info
                if not uploader:
                    next_sibling = link.next_sibling
                    if next_sibling and isinstance(next_sibling, str):
                        sibling_text = next_sibling.strip()
                        if sibling_text:
                            uploader = sibling_text.strip('(), ')

                images.append({
                    'url': img_url,
                    'metadata': {
                        **metadata,
                        'uploader': uploader or 'Unknown',
                        'link_text': link_text,
                        'image_context': 'photos_section',
                        'source': 'meteoritical_bulletin'
                    }
                })

            # Also check if the link contains an img tag
            img_tag = link.find('img')
            if img_tag:
                src = img_tag.get('src', '')
                if src and not src.startswith('data:'):
                    # Often thumbnails link to larger images
                    full_img_url = urljoin(page_url, href) if href else urljoin(page_url, src)

                    # Try to extract uploader
                    uploader = None
                    parent_text = link.parent.get_text() if link.parent else ''

                    if '(' in parent_text and ')' in parent_text:
                        match = re.search(r'\(([^)]+)\)', parent_text)
                        if match:
                            uploader = match.group(1).strip()

                    images.append({
                        'url': full_img_url,
                        'metadata': {
                            **metadata,
                            'uploader': uploader or 'Unknown',
                            'alt_text': img_tag.get('alt', ''),
                            'image_context': 'photos_section',
                            'source': 'meteoritical_bulletin'
                        }
                    })

        return images

    def get_images(self, listing_url=None, max_meteorites=None):
        """
        Get images from the meteorite listing page.

        Args:
            listing_url: URL of the listing page (defaults to LISTING_URL)
            max_meteorites: Maximum number of meteorites to scrape (None = all)

        Returns:
            List of image dictionaries with metadata
        """
        # Get list of meteorites from the listing page
        used_listing_url = listing_url or self.LISTING_URL
        meteorite_links = self.scrape_meteorite_listing(listing_url)

        if not meteorite_links:
            logger.warning("No meteorites found in listing")
            return []

        # Limit if requested
        if max_meteorites:
            meteorite_links = meteorite_links[:max_meteorites]

        all_images = []
        total = len(meteorite_links)

        for idx, (name, url) in enumerate(meteorite_links, 1):
            logger.info(f"[{idx}/{total}] Scraping photos for: {name}")

            try:
                self.driver.get(url)
                time.sleep(1)  # Wait for page to load

                images = self.parse_meteorite_page(self.driver.page_source, url)

                if images:
                    logger.info(f"  Found {len(images)} photo(s)")
                    all_images.extend(images)
                else:
                    logger.info(f"  No photos found")

            except Exception as e:
                logger.error(f"  Error scraping {name}: {e}")

            # Be respectful with rate limiting
            time.sleep(1)

        logger.info(f"Total images collected: {len(all_images)}")
        return all_images

    def close(self):
        """Close the Selenium driver"""
        if hasattr(self, 'driver'):
            logger.info("Closing Selenium driver...")
            self.driver.quit()

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()

    def __del__(self):
        """Cleanup on deletion"""
        self.close()
