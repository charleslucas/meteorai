# Meteorite Image Scraper

A Python-based web scraper for collecting meteorite images from scientific databases and museums to train AI models for meteorite detection.

## Setup

See [SETUP.md](../docs/SETUP.md) for full installation and configuration instructions (PostgreSQL, Python dependencies, environment file, and service startup).

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

### Batch scraping with resume support:
```bash
# Scrape up to 50 meteorites starting at position 100 in the listing
python main.py --start-at 100 --max-meteorites 50

# Run headless (not recommended â€” more likely to be blocked by Cloudflare)
python main.py --headless
```

### List all meteorites in the database:
```bash
python list_database.py
```

### Test scrape (2 meteorites only, useful for verifying setup):
```bash
python test_scraper.py
```

### Browse and edit meteorites (Streamlit app):
```bash
streamlit run app.py
```
Opens a local web UI where you can:
- Browse meteorites in a paginated table
- Filter by name, primary type, image context, or needs-review status
- View meteorite images and edit all metadata fields
- Add new meteorites by pasting an image URL (downloaded automatically)
- Add frames from a YouTube video using the built-in frame picker (see below)
- Delete a meteorite (removes the database record, image file, and JSON sidecar)

### Adding images from YouTube videos:

In the Streamlit app, go to **New Meteorite** and paste a YouTube URL into the Image URL field. The app will:

1. **Download** the video to `meteorite_scraper/videos/` using `yt-dlp`
2. **Launch** a separate OpenCV frame picker window
3. Let you **navigate** the video and **capture** frames with the keyboard:

| Key | Action |
|-----|--------|
| `Space` | Play / Pause |
| `C` | Capture current frame |
| `. / â†’` | Step forward 1 frame |
| `, / â†` | Step backward 1 frame |
| `D` | Jump forward 5 seconds |
| `A` | Jump backward 5 seconds |
| `Q / Esc` | Quit and return to browser |

4. **Review** captured frame thumbnails in the browser and uncheck any to discard
5. **Save** selected frames to the database with all metadata from the form

Requires additional dependencies:
```bash
pip install yt-dlp opencv-python
```

## Annotation Workflow

Images collected by the scraper are annotated in Label Studio and exported for model training.

1. **Set up the Label Studio project** (one-time):
   ```bash
   python label_studio/setup_project.py --api-key YOUR_LEGACY_TOKEN
   ```
   Then add `LABEL_STUDIO_API_KEY` and `LABEL_STUDIO_PROJECT_ID` to `meteorite_scraper/.env` â€” after that, new images are pushed to Label Studio automatically when saved via the Streamlit app.
2. **Annotate** images in the browser at http://localhost:8080 using bounding boxes and/or polygons. The SAM ML backend (port 9090) provides automatic pre-labeling and interactive smart-tool annotation.
3. **Export** annotations when ready to train:
   ```bash
   python label_studio/export_annotations.py --project-id 1 --username you@email.com --password yourpwd --format both
   ```
   Exports saved to `label_studio/exports/yolo/` and `label_studio/exports/coco/`.

See [EXPORT.md](../docs/EXPORT.md) for backup and restore instructions.

## Project Structure
```
meteorai/
â”œâ”€â”€ start_services.ps1              # Start all services
â”œâ”€â”€ stop_services.ps1               # Stop all services
â”œâ”€â”€ start_services.bat              # Double-click launcher for start_services.ps1
â”œâ”€â”€ stop_services.bat               # Double-click launcher for stop_services.ps1
â”œâ”€â”€ export_backup.py                # Export full backup (DB + images + videos + annotations)
â”œâ”€â”€ import_backup.py                # Merge backup into another installation
â”œâ”€â”€ README_EXPORT.md                # Backup/restore documentation
â”œâ”€â”€ label_studio/                   # Label Studio annotation integration
â”‚   â”œâ”€â”€ setup_project.py            # Create LS project and import images as tasks
â”‚   â”œâ”€â”€ export_annotations.py       # Export annotations to YOLO/COCO format
â”‚   â”œâ”€â”€ fix_task_urls.py            # Fix image URL paths in existing LS tasks
â”‚   â”œâ”€â”€ sync_task_metadata.py       # Backfill metadata on tasks created by storage sync
â”‚   â”œâ”€â”€ sam_backend.py              # SAM ML backend for automatic pre-labeling
â”‚   â”œâ”€â”€ start_sam_backend.bat       # Start the SAM backend server
â”‚   â”œâ”€â”€ stop_sam_backend.bat        # Stop the SAM backend server
â”‚   â”œâ”€â”€ download_sam_weights.py     # Download SAM model weights
â”‚   â”œâ”€â”€ requirements_sam.txt        # Additional dependencies for SAM
â”‚   â”œâ”€â”€ sam_weights/                # SAM model checkpoint files (downloaded separately)
â”‚   â””â”€â”€ exports/                    # Exported annotation files (YOLO/COCO)
â”œâ”€â”€ database/
â”‚   â””â”€â”€ migrations/                 # SQL migration scripts
â””â”€â”€ meteorite_scraper/
    â”œâ”€â”€ config.py                   # Configuration settings
    â”œâ”€â”€ database.py                 # Database operations
    â”œâ”€â”€ scraper.py                  # Main scraper logic
    â”œâ”€â”€ utils.py                    # Helper functions
    â”œâ”€â”€ main.py                     # CLI entry point for web scraping
    â”œâ”€â”€ app.py                      # Streamlit browser/editor UI
    â”œâ”€â”€ youtube_picker.py           # OpenCV frame picker (launched by app.py)
    â”œâ”€â”€ list_database.py            # Print all database records to the console
    â”œâ”€â”€ test_scraper.py             # Quick test â€” scrapes 2 meteorites only
    â”œâ”€â”€ sources/                    # Source-specific scrapers
    â”‚   â””â”€â”€ meteoritical_bulletin.py
    â”œâ”€â”€ images/                     # Downloaded meteorite images
    â”œâ”€â”€ videos/                     # Downloaded YouTube videos
    â”œâ”€â”€ yt_staging/                 # Temporary staging for captured video frames
    â”œâ”€â”€ metadata/                   # JSON metadata sidecars
    â””â”€â”€ logs/                       # Log files
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
