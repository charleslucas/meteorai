# Meteorite Image Scraper

A Python-based web scraper for collecting meteorite images from scientific databases and museums to train AI models for meteorite detection.

## Setup

See [SETUP.md](SETUP.md) for full installation and configuration instructions (PostgreSQL, Python dependencies, environment file, and service startup).

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

### Browse and edit meteorites (Streamlit app):
```bash
streamlit run app.py
```
Opens a local web UI where you can:
- Browse meteorites in a paginated table
- Filter by name, primary type, image context, or needs-review status
- View meteorite images and edit all metadata fields
- Add new meteorites by URL with image download
- Delete a meteorite (removes the database record, image file, and JSON sidecar)

## Project Structure
```
meteorai/
├── start_services.ps1         # Start all services (PostgreSQL, Streamlit, Label Studio)
├── stop_services.ps1          # Stop all services
├── label_studio/              # Label Studio annotation integration
│   ├── setup_project.py       # Create LS project and import images
│   ├── export_annotations.py  # Export annotations to YOLO/COCO format
│   └── exports/               # Exported annotation files
├── database/
│   └── migrations/            # SQL migration scripts
└── meteorite_scraper/
    ├── config.py              # Configuration settings
    ├── database.py            # Database operations
    ├── scraper.py             # Main scraper logic
    ├── utils.py               # Helper functions
    ├── main.py                # Entry point
    ├── app.py                 # Streamlit browser/editor UI
    ├── sources/               # Source-specific scrapers
    │   └── meteoritical_bulletin.py
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
