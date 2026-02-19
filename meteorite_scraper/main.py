#!/usr/bin/env python3
"""
Main entry point for the meteorite image scraper
"""

import argparse
import logging
from scraper import MeteoriteImageScraper
from sources.meteoritical_bulletin import MeteoriticalBulletinScraper
from sources.nasa_curator import NASACuratorScraper
from sources.museum_scraper import MuseumScraper
from utils import setup_logging

def main():
    parser = argparse.ArgumentParser(description='Scrape meteorite images from various sources')
    parser.add_argument(
        '--source',
        choices=['all', 'meteoritical', 'nasa', 'museums'],
        default='all',
        help='Which source to scrape'
    )
    parser.add_argument(
        '--meteorites',
        nargs='+',
        help='Specific meteorite names to search for'
    )
    parser.add_argument(
        '--stats',
        action='store_true',
        help='Print database statistics and exit'
    )
    parser.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        default='INFO',
        help='Logging level'
    )
    parser.add_argument(
        '--headless',
        action='store_true',
        help='Run browser in headless mode (not recommended - Cloudflare detection is more likely)'
    )
    parser.add_argument(
        '--no-headless',
        dest='headless',
        action='store_false',
        help='Run browser with visible window (recommended for Cloudflare bypass)'
    )
    parser.set_defaults(headless=False)

    args = parser.parse_args()
    
    # Setup logging
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.setLevel(getattr(logging, args.log_level))
    
    # Create scraper
    scraper = MeteoriteImageScraper()
    
    # Just print stats if requested
    if args.stats:
        scraper.print_statistics()
        return
    
    # Scrape from selected sources
    if args.source in ['all', 'meteoritical']:
        logger.info("Scraping Meteoritical Bulletin")
        bulletin_scraper = MeteoriticalBulletinScraper(headless=args.headless)
        if args.meteorites:
            bulletin_scraper.meteorite_names = args.meteorites
        scraper.scrape_source(bulletin_scraper, 'meteoritical_bulletin')
    
    if args.source in ['all', 'nasa']:
        logger.info("Scraping NASA collections")
        nasa_scraper = NASACuratorScraper(scraper.session)
        scraper.scrape_source(nasa_scraper, 'nasa_curator')
    
    if args.source in ['all', 'museums']:
        logger.info("Scraping museum collections")
        museum_scraper = MuseumScraper('https://example.com', scraper.session)
        scraper.scrape_source(museum_scraper, 'museums')
    
    # Print final statistics
    scraper.print_statistics()

if __name__ == "__main__":
    main()
