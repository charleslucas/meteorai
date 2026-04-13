# MeteorAI Backup & Restore Guide

The `export_backup.py` and `import_backup.py` scripts create and restore portable ZIP backups of the entire MeteorAI dataset. Backups include the meteorite database, images, and Label Studio annotations. Imports are always additive — existing data is never overwritten or deleted; only new records are added.

---

## Prerequisites

- Python dependencies installed (`pip install -r meteorite_scraper/requirements.txt`)
- PostgreSQL `pg_dump` / `psql` on PATH, e.g.:
  ```powershell
  $env:PATH += ";C:\Program Files\PostgreSQL\18\bin"
  ```
- Services running when exporting (PostgreSQL required; Label Studio required only if exporting annotations)

---

## Export

Creates a timestamped ZIP containing the database schema, all meteorite records, images, and Label Studio annotations.

### Basic export (database + images only)

```bash
python export_backup.py
```

Output: `meteorai_backup_YYYYMMDD_HHMMSS.zip` in the project root.

### Export including Label Studio annotations

```bash
python export_backup.py --ls-project-id 1 --ls-username your@email.com --ls-password yourpwd
```

### Export to a specific path

```bash
python export_backup.py --output backups/my_backup.zip
```

### Skip Label Studio (faster if annotations not needed)

```bash
python export_backup.py --skip-label-studio
```

### Skip videos (omit downloaded YouTube videos to keep the archive smaller)

```bash
python export_backup.py --skip-videos
```

### All options

| Flag | Default | Description |
|------|---------|-------------|
| `--output PATH` | `meteorai_backup_TIMESTAMP.zip` | Output ZIP file path |
| `--ls-url URL` | `http://localhost:8080` | Label Studio base URL |
| `--ls-project-id N` | *(none)* | Label Studio project ID to export |
| `--ls-username EMAIL` | *(none)* | Label Studio login email |
| `--ls-password PWD` | *(none)* | Label Studio login password |
| `--skip-label-studio` | false | Omit Label Studio export entirely |
| `--skip-videos` | false | Omit downloaded YouTube videos (can be large) |

### ZIP contents

```
meteorai_backup_YYYYMMDD_HHMMSS.zip
├── manifest.json                   # Metadata: date, record/image/video counts
├── env_reference.json              # DB connection info (passwords masked)
├── schema.sql                      # Database schema (pg_dump --schema-only)
├── data.json                       # All meteorite rows as JSON
├── images/                         # All meteorite image files
│   ├── abc123_meteorite.jpg
│   └── ...
├── videos/                         # Downloaded YouTube videos (omitted with --skip-videos)
│   ├── dQw4w9WgXcQ.mp4
│   └── ...
└── label_studio_annotations.json   # LS project config + all tasks/annotations
                                    # (only present when --ls-project-id is given)
```

---

## Import

Merges a backup ZIP into any MeteorAI installation (fresh or existing). The database user and database are created automatically if they do not exist.

### Basic import (prompts for passwords)

```bash
python import_backup.py meteorai_backup_20250101_120000.zip
```

### Import including Label Studio annotations

```bash
python import_backup.py backup.zip --ls-username your@email.com --ls-password yourpwd
```

### Import into an existing Label Studio project

```bash
python import_backup.py backup.zip --ls-username your@email.com --ls-password yourpwd --ls-project-id 2
```

### Skip Label Studio during import

```bash
python import_backup.py backup.zip --skip-label-studio
```

### Supply passwords non-interactively (e.g. in scripts)

```bash
python import_backup.py backup.zip --db-password gingerclover --pg-superuser-password postgres_pw
```

### Override image or video destination

```bash
python import_backup.py backup.zip --images-dir /mnt/data/meteorai/images
python import_backup.py backup.zip --videos-dir /mnt/data/meteorai/videos
```

### Skip videos during import

```bash
python import_backup.py backup.zip --skip-videos
```

### All options

| Flag | Default | Description |
|------|---------|-------------|
| `backup` | *(required)* | Path to the backup ZIP file |
| `--db-host HOST` | `localhost` | Target PostgreSQL host |
| `--db-port PORT` | `5432` | Target PostgreSQL port |
| `--db-name NAME` | `meteorite_images` | Target database name |
| `--db-user USER` | `meteorite_user` | Application DB user (created if absent) |
| `--db-password PWD` | *(prompted)* | Password for the application DB user |
| `--pg-superuser USER` | `postgres` | PostgreSQL superuser for DB/user creation |
| `--pg-superuser-password PWD` | *(prompted)* | Superuser password |
| `--ls-url URL` | `http://localhost:8080` | Label Studio base URL |
| `--ls-project-id N` | *(none)* | Import into an existing LS project; creates a new project if omitted |
| `--ls-username EMAIL` | *(none)* | Label Studio login email |
| `--ls-password PWD` | *(none)* | Label Studio login password |
| `--skip-label-studio` | false | Omit Label Studio import entirely |
| `--images-dir PATH` | `meteorite_scraper/images/` | Override target images directory |
| `--videos-dir PATH` | `meteorite_scraper/videos/` | Override target videos directory |
| `--skip-videos` | false | Omit video restore entirely |

---

## Duplicate handling

Imports are always safe to run against a database that already has data.

| Data type | Deduplication key | Behavior when duplicate found |
|-----------|-------------------|-------------------------------|
| Meteorite DB record | `source_url` (falls back to `stored_filename` for manually-added records) | Skipped |
| Image file | Filename | Skipped (existing file kept) |
| Video file | Filename | Skipped (existing file kept) |
| Label Studio task | `stored_filename` in task data | Skipped |
| Label Studio task with no DB record | `stored_filename` not in target DB | Skipped (orphan protection) |

For YouTube-sourced frames, `source_url` is stored as `{youtube_url}#t={timestamp}` — each captured frame has a unique, stable identifier that prevents duplicate inserts across imports.

`image_id` values in Label Studio task data are automatically remapped to the target database's IDs after the DB merge, so the link between annotations and database records is always consistent.

---

## Typical workflows

### Back up before a scraping run

```bash
python export_backup.py --ls-project-id 1 --ls-username you@email.com --ls-password yourpwd
```

### Transfer to another machine

1. Copy the ZIP to the new machine.
2. Install dependencies and start PostgreSQL.
3. Run the import:
   ```bash
   python import_backup.py meteorai_backup_20250101_120000.zip \
       --ls-username you@email.com --ls-password yourpwd
   ```
4. Start all services:
   ```powershell
   .\start_services.bat
   ```

### Merge two datasets

If both machines have scraped different images, export from each and import into the other. Duplicate `source_url` records are skipped automatically.

```bash
# On machine A: import machine B's data
python import_backup.py machineB_backup.zip

# On machine B: import machine A's data
python import_backup.py machineA_backup.zip
```
