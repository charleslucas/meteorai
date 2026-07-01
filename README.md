# MeteorAI

End-to-end pipeline for collecting, annotating, and training AI models to detect meteorites in images.

## What it does

1. **Scrape** meteorite images from the Meteoritical Bulletin and other sources
2. **Store** them in PostgreSQL with metadata (type, location, source URL, photographer, etc.)
3. **Annotate** bounding boxes in Label Studio — meteorite body, fusion crust, regmaglypts, scale reference
4. **Train** a YOLOv8 detection model on the annotations
5. **Auto-annotate** new images with the trained model (active learning loop)
6. **Sort** a directory of unsorted meteorite photos into useful vs. not using a scene classifier

The Streamlit app (`meteorite_scraper/app.py`) is the main UI for browsing images, adding new ones, and managing the pipeline.

## Getting started

### Prerequisites

- Python 3.11+
- PostgreSQL 18 (Windows service `postgresql-x64-18`)
- Git

### First-time setup

See **[docs/SETUP.md](docs/SETUP.md)** for full installation and configuration: Python dependencies, PostgreSQL setup, `.env` config, and starting all services.

### Moving to a new machine

See **[docs/MIGRATION.md](docs/MIGRATION.md)** for the automated machine-to-machine migration guide (`scripts/migrate_data.ps1`).

## Services

Start everything with one command from the project root:

```powershell
.\start_services.ps1
```

| Service | Port | URL |
|---------|------|-----|
| Streamlit app | 8501 | http://localhost:8501 |
| Label Studio | 8081 | http://localhost:8081 |
| PostgreSQL | 5432 | — |
| SAM ML backend | 9090 | http://localhost:9090 |

## Documentation

| Doc | Contents |
|-----|----------|
| [docs/METHODOLOGY.md](docs/METHODOLOGY.md) | Detection approach: published research, low-data strategies, architecture choices |
| [docs/RESEARCH_REPORT.md](docs/RESEARCH_REPORT.md) | Full literature survey: papers, datasets, and per-paper notes |
| [docs/SETUP.md](docs/SETUP.md) | Environment setup: PostgreSQL, Python, Label Studio, `.env` |
| [docs/WORKFLOW.md](docs/WORKFLOW.md) | Full annotation + training loop: sort → import → annotate → train → repeat |
| [docs/TRAINING.md](docs/TRAINING.md) | Model training guide and tips |
| [docs/LABEL_STUDIO.md](docs/LABEL_STUDIO.md) | Label Studio setup, SAM backend, sync |
| [docs/EXPORT.md](docs/EXPORT.md) | Backup and restore (`export_backup.py` / `import_backup.py`) |
| [docs/MIGRATION.md](docs/MIGRATION.md) | Moving the full installation to a new machine |
| [docs/PROGRESS.md](docs/PROGRESS.md) | Current data counts, annotation status, and next steps |

## Project layout

```
meteorai/
├── README.md
├── start_services.ps1 / .bat       # Start all services
├── stop_services.ps1 / .bat        # Stop all services
├── start_label_studio.bat
├── scripts/                        # Pipeline scripts
│   ├── train_model.py              # Export annotations → train YOLOv8
│   ├── auto_annotate.py            # Push model predictions to Label Studio
│   ├── import_images.py            # Import sorted images into the pipeline
│   ├── sort_media.py               # Classify unsorted photos → sorted_in_situ/
│   ├── train_classifier.py         # Train the scene classifier
│   ├── export_backup.py            # Backup DB + images + annotations to ZIP
│   ├── import_backup.py            # Restore from backup ZIP
│   └── migrate_data.ps1            # Machine-to-machine migration
├── docs/                           # Documentation
├── meteorite_scraper/              # Scraper, database, Streamlit app
├── label_studio/                   # Label Studio integration + SAM backend
├── training/                       # Dataset splits, model runs, best_model.txt
├── sorted_in_situ/                 # Curated in-situ images ready to import
├── sorted_not_in_situ/             # Rejected images (kept for reference)
└── unsorted_media/                 # Drop unsorted photos here, run sort_media.py
```
