# Meteorite Image Scraper

A Python-based web scraper for collecting meteorite images from scientific databases and museums to train AI models for meteorite detection.

## Setup

1. Install PostgreSQL and create the database (see setup instructions)

2. Install Python dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file with your database credentials:
```
DB_HOST=localhost
DB_NAME=meteorite_images
DB_USER=meteorite_user
DB_PASSWORD=YourPassword
DB_PORT=5432
```

4. Run the schema to create tables (if not already done)

## Usage

### Scrape all sources:
```bash
python main.py
```

### Scrape specific source:
```bash
python main.py --source meteoritical
```

### Search for specific meteorites:
```bash
python main.py --source meteoritical --meteorites Allende Murchison Chelyabinsk
```

### View statistics:
```bash
python main.py --stats
```

### Enable debug logging:
```bash
python main.py --log-level DEBUG
```

## Project Structure
```
meteorite_scraper/
├── config.py              # Configuration settings
├── database.py            # Database operations
├── scraper.py             # Main scraper logic
├── utils.py               # Helper functions
├── main.py                # Entry point
├── sources/               # Source-specific scrapers
│   ├── meteoritical_bulletin.py
│   ├── nasa_curator.py
│   └── museum_scraper.py
├── images/                # Downloaded images
├── metadata/              # JSON metadata files
└── logs/                  # Log files
```

## Adding New Sources

To add a new scraping source:

1. Create a new file in `sources/` (e.g., `sources/my_source.py`)
2. Create a class with a `get_images()` method that returns a list of dicts:
```python
   [{
       'url': 'image_url',
       'metadata': {
           'meteorite_name': 'Name',
           'classification': 'H5',
           # ... other fields
       }
   }]
```
3. Add it to `main.py`

## Notes

- Respects robots.txt and implements rate limiting
- Stores metadata in both PostgreSQL and JSON for easy editing
- Validates images before storing
- Tracks duplicate URLs to avoid re-downloading
- Logs all scraping sessions

## License

Educational/Research use only. Respect source website terms of service.