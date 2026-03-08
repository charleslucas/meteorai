# MeteorAI Setup Guide

## 1. Install PostgreSQL

1. Download and install PostgreSQL from https://www.postgresql.org/downloads/
   - Windows: Use the installer from EnterpriseDB
   - macOS: `brew install postgresql`

2. During installation, note the superuser (postgres) password you set.

3. Create the database and user. Open a terminal and run:
```bash
psql -U postgres
```

Then in the psql prompt:
```sql
CREATE USER meteorite_user WITH PASSWORD 'YourPassword';
CREATE DATABASE meteorite_images OWNER meteorite_user;
GRANT ALL PRIVILEGES ON DATABASE meteorite_images TO meteorite_user;
\q
```

4. Run the schema to create tables:
```bash
psql -U meteorite_user -d meteorite_images -f meteorite_scraper/schema.sql
```

## 2. Install Python Dependencies

```bash
pip install -r meteorite_scraper/requirements.txt
```

This installs all required packages including Streamlit, Label Studio, and the Label Studio SDK.

## 3. Create Environment File

Create a `.env` file in the `meteorite_scraper/` directory with your database credentials:
```
DB_HOST=localhost
DB_NAME=meteorite_images
DB_USER=meteorite_user
DB_PASSWORD=YourPassword
DB_PORT=5432
```

## 4. Starting Services

### Using the startup script (recommended)

From PowerShell, run:
```powershell
.\start_services.ps1
```

This starts all three services and opens the web UIs in your browser. The script detects if a service is already running and skips it.

To stop all services:
```powershell
.\stop_services.ps1
```

### Starting services manually

**PostgreSQL:**
```powershell
# Windows
& "C:\Program Files\PostgreSQL\18\bin\pg_ctl" start -D "C:\Program Files\PostgreSQL\18\data"

# macOS
brew services start postgresql
```

**Streamlit** (meteorite browser/editor on port 8501):
```bash
streamlit run meteorite_scraper/app.py --server.port 8501
```

**Label Studio** (annotation tool on port 8080):
```powershell
# Windows (PowerShell)
$env:LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED="true"
$env:LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT="C:/cygwin64/home/charl/meteorai/meteorite_scraper"
label-studio start --port 8080
```
```bash
# macOS/Linux
LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED=true \
LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT=/path/to/meteorai/meteorite_scraper \
label-studio start --port 8080
```

Note: The `LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED` and `LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT` environment variables are required so Label Studio can serve images directly from the images directory.

## 5. Label Studio First-Time Setup

1. Open http://localhost:8080 and create a local account.
2. Go to Account & Settings and copy your API key.
3. Run the project setup script to import all meteorite images:
```bash
python label_studio/setup_project.py --api-key YOUR_API_KEY
```
4. Open the "Meteorite Annotation" project in Label Studio and begin annotating.

## 6. Exporting Annotations

After annotating images in Label Studio, export to YOLO and/or COCO format:
```bash
python label_studio/export_annotations.py --project-id 1 --api-key YOUR_API_KEY --format both
```

Exports are saved to `label_studio/exports/yolo/` and `label_studio/exports/coco/`.

## Service URLs

| Service       | URL                    | Port |
|---------------|------------------------|------|
| Streamlit     | http://localhost:8501  | 8501 |
| Label Studio  | http://localhost:8080  | 8080 |
| PostgreSQL    | localhost              | 5432 |
