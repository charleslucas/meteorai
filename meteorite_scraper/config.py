import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Project paths
BASE_DIR = Path(__file__).parent
IMAGES_DIR = BASE_DIR / "images"
METADATA_DIR = BASE_DIR / "metadata"
LOGS_DIR = BASE_DIR / "logs"

# Create directories if they don't exist
IMAGES_DIR.mkdir(exist_ok=True)
METADATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'database': os.getenv('DB_NAME', 'meteorite_images'),
    'user': os.getenv('DB_USER', 'meteorite_user'),
    'password': os.getenv('DB_PASSWORD', 'your_password_here'),
    'port': os.getenv('DB_PORT', '5432')
}

# Scraping configuration
#SCRAPE_CONFIG = {
#    'user_agent': 'MeteoriteResearchBot/1.0 (Educational Research; Contact: your_email@example.com)',
#    'request_timeout': 30,
#    'rate_limit_delay': 2,  # seconds between requests
#    'max_retries': 3,
#    'chunk_size': 8192,  # for image downloads
#}

SCRAPE_CONFIG = {
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'request_timeout': 30,
    'rate_limit_delay': 3,  # Increase delay to 3 seconds
    'max_retries': 3,
    'chunk_size': 8192,
    'headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Cache-Control': 'max-age=0',
    }
}

# Image processing
IMAGE_CONFIG = {
    'min_width': 200,
    'min_height': 200,
    'max_file_size_mb': 50,
    'allowed_formats': ['jpg', 'jpeg', 'png', 'gif', 'webp']
}
