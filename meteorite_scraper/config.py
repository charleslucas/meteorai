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
SCRAPE_CONFIG = {
    'user_agent': 'MeteoriteResearchBot/1.0 (Educational Research; Contact: your_email@example.com)',
    'request_timeout': 30,
    'rate_limit_delay': 2,  # seconds between requests
    'max_retries': 3,
    'chunk_size': 8192,  # for image downloads
}

# Image processing
IMAGE_CONFIG = {
    'min_width': 200,
    'min_height': 200,
    'max_file_size_mb': 50,
    'allowed_formats': ['jpg', 'jpeg', 'png', 'gif', 'webp']
}
