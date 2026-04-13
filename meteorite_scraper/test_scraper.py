#!/usr/bin/env python3
"""
Test scraper with just a few meteorites
"""

import logging
from scraper import MeteoriteImageScraper
from sources.meteoritical_bulletin import MeteoriticalBulletinScraper
from utils import setup_logging

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

def main():
    print("Starting test scrape with just 2 meteorites...")

    # Create scraper
    scraper = MeteoriteImageScraper()

    # Create Meteoritical Bulletin scraper (non-headless for Cloudflare bypass)
    # Pass database instance for duplicate checking
    bulletin_scraper = MeteoriticalBulletinScraper(headless=False, db=scraper.db)

    try:
        # Get images - but limit to just 2 meteorites for testing
        logger.info("Getting images (limited to 2 meteorites for testing)...")
        images = bulletin_scraper.get_images(max_meteorites=2)

        logger.info(f"Got {len(images)} total image URLs")

        # Process each image
        for idx, image_data in enumerate(images, 1):
            logger.info(f"\n[{idx}/{len(images)}] Processing image...")
            logger.info(f"  URL: {image_data['url']}")
            logger.info(f"  Meteorite: {image_data['metadata'].get('meteorite_name')}")
            logger.info(f"  Uploader: {image_data['metadata'].get('uploader')}")

            # Actually download and process the image
            result = scraper.process_image(image_data['url'], image_data['metadata'])

            if result:
                logger.info(f"  [OK] Successfully saved as image_id {result}")
            else:
                logger.warning(f"  [FAIL] Failed to save image")

        # Print final stats
        print("\n" + "="*80)
        print("FINAL STATISTICS:")
        print(f"  Images found: {scraper.stats['images_found']}")
        print(f"  Images downloaded: {scraper.stats['images_downloaded']}")
        print(f"  Images skipped: {scraper.stats['images_skipped']}")
        print(f"  Errors: {scraper.stats['errors']}")
        print("="*80)

    finally:
        bulletin_scraper.close()

if __name__ == "__main__":
    main()
