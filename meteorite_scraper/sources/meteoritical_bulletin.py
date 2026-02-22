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
            #logger.info("=" * 80)
            #logger.info("Received HTML:")
            #logger.info("*************************************************")
            #logger.info(self.driver.page_source)
            #logger.info("*************************************************")
            #logger.info("=" * 80)

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
            # Check if this row has a <th> tag (header cell)
            header_cell = row.find('th')
            if header_cell:
                key = header_cell.text.strip().rstrip(':').lower()

                # Check if this is the Photos section
                if key == 'photos' or 'photo' in key:
                    # The content is in the <td> cell
                    content_cell = row.find('td')
                    if content_cell:
                        photos_data = self._parse_photos_cell(content_cell, page_url, metadata)
                        images.extend(photos_data)
                        logger.info(f"Found {len(photos_data)} photos for {metadata.get('meteorite_name')}")
                    continue

            # Also check regular td cells for other metadata
            cells = row.find_all('td')
            if len(cells) >= 2:
                key = cells[0].text.strip().rstrip(':').lower()
                value = cells[1].text.strip()

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
        The Photos cell contains a nested table with photographer names and photo links.
        Each thumbnail link points to a page with the full-resolution image.
        """
        images = []

        # Look for the nested table with class "text-table"
        photo_table = photos_cell.find('table', class_='text-table')

        if not photo_table:
            logger.debug("No photo table found in Photos cell")
            return images

        # Find all data rows in the photo table
        for row in photo_table.find_all('tr'):
            # Skip header rows (they have <th> tags)
            if row.find('th'):
                continue

            cells = row.find_all('td')

            # Each data row should have 2 cells: photographer name and photos
            if len(cells) >= 2:
                # First cell contains photographer name
                photographer_cell = cells[0]
                photographer_link = photographer_cell.find('a')
                uploader = photographer_link.text.strip() if photographer_link else photographer_cell.text.strip()

                # Second cell contains photo thumbnails
                photos_cell_data = cells[1]

                # Find all thumbnail links (they link to get_original_photo.cfm)
                for link in photos_cell_data.find_all('a', class_='thumbnail'):
                    href = link.get('href', '')

                    if href and 'get_original_photo' in href:
                        # Build full URL to the photo detail page
                        photo_page_url = urljoin(page_url, href)

                        # Get the thumbnail image for additional metadata
                        img_tag = link.find('img')
                        title = img_tag.get('title', '') if img_tag else ''

                        # Note: photo_page_url points to get_original_photo.cfm
                        # which displays the full-resolution image
                        # The scraper will need to follow this URL to get the actual image
                        images.append({
                            'url': photo_page_url,
                            'metadata': {
                                **metadata,
                                'uploader': uploader,
                                'title': title,
                                'image_context': 'photos_section',
                                'source': 'meteoritical_bulletin',
                                'is_photo_page': True  # Flag indicating this needs resolution
                            }
                        })
                        logger.debug(f"Found photo page: {photo_page_url} by {uploader}")

        logger.info(f"Extracted {len(images)} photo URLs from Photos section")
        return images

    def resolve_photo_page(self, photo_page_url):
        """
        Visit a photo detail page and extract the actual full-resolution image URL.

        Args:
            photo_page_url: URL to the get_original_photo.cfm page

        Returns:
            The actual image URL, or None if not found
        """
        try:
            logger.debug(f"Resolving photo page: {photo_page_url}")
            self.driver.get(photo_page_url)
            time.sleep(1)  # Wait for page to load

            # Parse the photo detail page
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')

            # Strategy 1: Look for the "Direct link to photo" button
            # This is the most reliable method for this site
            direct_link = soup.find('a', class_='button-darkblue')
            if direct_link and direct_link.get('href'):
                actual_url = direct_link['href']
                # The href might be HTML-encoded, decode it
                import html
                actual_url = html.unescape(actual_url)
                logger.debug(f"Found image URL from direct link button: {actual_url}")
                return actual_url

            # Strategy 2: Look for the main image in the content area
            # The image is in a <main> tag with role="main"
            main_content = soup.find('main', role='main')
            if main_content:
                img = main_content.find('img')
                if img and img.get('src'):
                    src = img['src']
                    # Check if it's a valid image URL
                    if any(ext in src.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp']):
                        actual_url = urljoin(photo_page_url, src)
                        logger.debug(f"Found image URL from main content: {actual_url}")
                        return actual_url

            # Strategy 3: Look for any img tag with src containing common image extensions
            # Skip logos and small images
            for img in soup.find_all('img'):
                src = img.get('src', '')
                if src and any(ext in src.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp']):
                    # Skip logos, thumbnails, and small images
                    if not any(skip in src.lower() for skip in ['logo', 'thumb', 'small', 'icon']):
                        actual_url = urljoin(photo_page_url, src)
                        logger.debug(f"Found image URL (fallback): {actual_url}")
                        return actual_url

            logger.warning(f"Could not find image on photo page: {photo_page_url}")
            return None

        except Exception as e:
            logger.error(f"Error resolving photo page {photo_page_url}: {e}")
            return None

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

        logger.info(f"Total photo pages collected: {len(all_images)}")

        # Resolve photo page URLs to actual image URLs
        logger.info("Resolving photo page URLs to actual images...")
        resolved_images = []
        for image_data in all_images:
            if image_data['metadata'].get('is_photo_page'):
                # This is a photo detail page, need to resolve it
                actual_url = self.resolve_photo_page(image_data['url'])
                if actual_url:
                    # Update with the actual image URL
                    image_data['url'] = actual_url
                    # Remove the flag since it's now resolved
                    image_data['metadata']['is_photo_page'] = False
                    resolved_images.append(image_data)
                    logger.debug(f"Resolved to: {actual_url}")
                else:
                    logger.warning(f"Failed to resolve photo page: {image_data['url']}")

                # Rate limiting between photo page visits
                time.sleep(1)
            else:
                # Already a direct image URL
                resolved_images.append(image_data)

        logger.info(f"Successfully resolved {len(resolved_images)} image URLs")
        return resolved_images

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
