try:
    import cloudscraper as requests
    USING_CLOUDSCRAPER = True
except ImportError:
    import requests
    USING_CLOUDSCRAPER = False
from bs4 import BeautifulSoup
import logging
import time
import re
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

class MeteoriticalBulletinScraper:
    """Scraper for the Meteoritical Bulletin Database"""

    BASE_URL = "https://www.lpi.usra.edu/meteor/"
    # Default listing URL for meteorites with photos
    LISTING_URL = "https://www.lpi.usra.edu/meteor/metbull.cfm?sfor=names&stype=contains&sea=*&country=All&categ=All&ants=no&falls=yes&nwas=no&phot=yes&map=ge&srt=name&page=0&lrec=1000&pnt=Normal+table&mblist=All&snew=0"

    def __init__(self, session=None):
        if session:
            self.session = session
        else:
            if USING_CLOUDSCRAPER:
                logger.info("Using cloudscraper to bypass bot detection")
                self.session = requests.create_scraper(
                    browser={
                        'browser': 'chrome',
                        'platform': 'windows',
                        'desktop': True
                    }
                )
            else:
                logger.info("Using standard requests (install cloudscraper for better bot detection bypass)")
                self.session = requests.Session()
                self.session.headers.update({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Sec-Fetch-User': '?1',
                    'Cache-Control': 'max-age=0'
                })
        self._session_initialized = False

    def _initialize_session(self):
        """Visit the homepage to establish session and get cookies"""
        if self._session_initialized:
            return

        try:
            logger.info("Initializing session by visiting homepage...")
            response = self.session.get(self.BASE_URL, timeout=30)
            response.raise_for_status()
            self._session_initialized = True
            logger.info("Session initialized successfully")
            time.sleep(1)  # Brief pause after homepage visit
        except Exception as e:
            logger.warning(f"Failed to initialize session: {e}")
            # Continue anyway, might still work
    
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
            # Add Referer header to look like we came from the homepage
            headers = {'Referer': self.BASE_URL}
            response = self.session.get(listing_url, headers=headers, timeout=30)
            logger.info(f"****************************************")
            logger.info(f"{response}")
            logger.info(f"****************************************")
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')
            meteorite_links = []

            # Find the table containing meteorite listings
            # Look for tables with meteorite data
            for table in soup.find_all('table'):
                rows = table.find_all('tr')

                # Try to find header row to identify the "Name" column
                header_row = None
                name_col_idx = None

                for row in rows:
                    headers = row.find_all('th')
                    if headers:
                        for idx, header in enumerate(headers):
                            if 'name' in header.text.strip().lower():
                                name_col_idx = idx
                                header_row = row
                                break
                        if name_col_idx is not None:
                            break

                # If we found a Name column, extract links from data rows
                if name_col_idx is not None:
                    for row in rows:
                        if row == header_row:
                            continue
                        cells = row.find_all('td')
                        if len(cells) > name_col_idx:
                            name_cell = cells[name_col_idx]
                            link = name_cell.find('a')
                            if link and link.get('href'):
                                meteorite_name = link.text.strip()
                                detail_url = urljoin(response.url, link['href'])
                                meteorite_links.append((meteorite_name, detail_url))
                                logger.debug(f"Found meteorite: {meteorite_name} -> {detail_url}")

            logger.info(f"Found {len(meteorite_links)} meteorites in listing")
            return meteorite_links

        except Exception as e:
            logger.error(f"Error scraping meteorite listing: {e}")
            return []

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
        """Parse a meteorite detail page and extract photos from the Photos section"""
        soup = BeautifulSoup(html_content, 'html.parser')

        images = []
        metadata = {'page_url': page_url}

        # Extract meteorite name
        title = soup.find('h1')
        if title:
            metadata['meteorite_name'] = title.text.strip()

        # Extract metadata from table
        in_photos_section = False
        for row in soup.find_all('tr'):
            cells = row.find_all('td')
            if len(cells) >= 2:
                key = cells[0].text.strip().rstrip(':').lower()
                value = cells[1].text.strip()

                # Check if we've entered the Photos section
                if key == 'photos' or 'photo' in key:
                    in_photos_section = True
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
                # Look for text near the link (could be in parentheses or nearby text)
                link_text = link.text.strip()
                parent_text = link.parent.get_text() if link.parent else ''

                # Common patterns: "photo by John Doe", "(John Doe)", "© John Doe"
                if '(' in parent_text and ')' in parent_text:
                    # Extract text in parentheses
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
                # Add Referer header to look like we came from the listing page
                headers = {'Referer': used_listing_url}
                response = self.session.get(url, headers=headers, timeout=30)
                logger.info(f"****************************************")
                logger.info(f"{response}")
                logger.info(f"****************************************")

                response.raise_for_status()
                images = self.parse_meteorite_page(response.content, url)

                if images:
                    logger.info(f"  Found {len(images)} photo(s)")
                    all_images.extend(images)
                else:
                    logger.info(f"  No photos found")

            except Exception as e:
                logger.error(f"  Error scraping {name}: {e}")

            # Be respectful with rate limiting
            time.sleep(2)

        logger.info(f"Total images collected: {len(all_images)}")
        return all_images

    def get_images_by_names(self, meteorite_names=None):
        """Get images for a list of specific meteorite names (legacy method)"""
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
