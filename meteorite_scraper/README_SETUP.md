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

### Optional: YouTube frame picker

To use the YouTube video frame picker in the Streamlit app (download videos and manually select frames as training images), install two additional packages:

```bash
pip install yt-dlp opencv-python
```

- `yt-dlp` — downloads videos from YouTube and other sites
- `opencv-python` — provides the frame picker window with keyboard controls

`ffmpeg` is also recommended for `yt-dlp` to merge the highest-quality video and audio streams:
```bash
# Windows: download from https://ffmpeg.org/download.html and add to PATH
# macOS:
brew install ffmpeg
```

Without `ffmpeg`, `yt-dlp` will fall back to a slightly lower-quality pre-merged format but still works.

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

Note: The `LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED` and `LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT` environment variables are required so Label Studio can serve images directly from the images directory. The document root must be set to the `meteorite_scraper/` directory (not the `images/` subdirectory).

## 5. Label Studio First-Time Setup

1. Open http://localhost:8080 and create a local account.
2. Go to **Account & Settings** and copy your **Legacy API Token** (not the JWT token).
3. Run the project setup script to create the annotation project and import all existing meteorite images as tasks:
```bash
python label_studio/setup_project.py --api-key YOUR_LEGACY_TOKEN
```
4. Add the following to `meteorite_scraper/.env` so the Streamlit app automatically pushes new images to Label Studio as they are added:
```
LABEL_STUDIO_API_KEY=YOUR_LEGACY_TOKEN
LABEL_STUDIO_PROJECT_ID=2
```
5. Open the **Meteorite Annotation** project in Label Studio and begin annotating.

**Automatic task creation:** Once the `.env` values are set, any image added via the Streamlit app (manual entry or YouTube frame picker) is pushed to Label Studio immediately — no manual sync or script needed.
   - Use **RectangleLabels** to draw bounding boxes around objects.
   - Use **PolygonLabels** for precise segmentation outlines.

**Available labels:** `meteorite`, `fusion_crust`, `regmaglypts`, `metal_flake`, `scale_reference`

## 6. SAM ML Backend (Auto-Annotation)

The SAM (Segment Anything Model) backend lets Label Studio automatically suggest annotations, dramatically speeding up the labeling process.

### First-time installation

#### Windows prerequisite: Visual Studio Build Tools

SAM 2 compiles native C++ extensions during installation and requires the MSVC compiler on Windows. Install **Visual Studio Build Tools 2022** (free, no full IDE needed) before proceeding:

1. Download from https://visualstudio.microsoft.com/downloads/ → "Tools for Visual Studio" → **Build Tools for Visual Studio 2022**
2. During setup, select the **"Desktop development with C++"** workload (~4 GB)

If you already have Visual Studio 2022 (any edition) installed, you already have what you need.

#### Install SAM 2 and dependencies

SAM 2 is not available on PyPI and must be installed directly from Meta's GitHub repository.

**No GPU (CPU-only):**
```bash
pip install git+https://github.com/facebookresearch/sam2.git
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install label-studio-ml opencv-python-headless scikit-image
```

**GPU with CUDA 12.x (e.g. RTX 30/40 series):**
```bash
pip install git+https://github.com/facebookresearch/sam2.git
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
pip install label-studio-ml opencv-python-headless scikit-image
```

**GPU with CUDA 12.8+ (e.g. RTX 50 series / Blackwell):**

RTX 50-series GPUs require CUDA 12.8 or later. PyTorch cu13x wheels do not yet exist, so use the cu128 nightly build:
```bash
# 1. Install CUDA Toolkit 12.8 from https://developer.nvidia.com/cuda-downloads
#    Select only "CUDA Toolkit" and "CUDA Development Tools".
#    Uncheck PhysX, GeForce Experience, and other optional components — not needed.
# 2. Install PyTorch nightly cu128
pip install --pre torch torchvision --index-url https://download.pytorch.org/whl/nightly/cu128
# 3. Install SAM 2 and remaining dependencies
pip install git+https://github.com/facebookresearch/sam2.git
pip install label-studio-ml opencv-python-headless scikit-image
```

Then download the model weights (~46 MB for the default "small" model):
```bash
python label_studio/download_sam_weights.py
```

Other model sizes are available if speed or accuracy needs differ:
```bash
python label_studio/download_sam_weights.py --model tiny   # fastest, ~39 MB
python label_studio/download_sam_weights.py --model large  # most accurate, ~224 MB
```

CPU inference is supported but slow (~10–30 seconds per image in automatic mode). A GPU with ≥2 GB VRAM is recommended for interactive use.

### Starting the SAM backend

The SAM backend starts automatically with the main service scripts once weights are downloaded:
```powershell
.\start_services.ps1
```

Or start it standalone (double-click or run from a terminal):
```cmd
python label_studio\sam_backend.py --port 9090
```

Keep the terminal window open — closing it stops the backend.

### Connecting to Label Studio

1. Open Label Studio and go to **Settings → Model → Connect Model**.
2. Enter URL: `http://localhost:9090`
3. Enable **"Interactive preannotations"** — this activates both automatic pre-labeling when you open an image and the interactive Smart tool. Without it, the backend is connected but won't generate any annotations.
4. Click **Validate and Save**.

### Annotation modes

**Automatic (batch):** When you open an unannotated image, a polygon and bounding box are pre-filled automatically. SAM selects the most prominent subject as the `meteorite` prediction. Review and correct as needed.

**Interactive (Smart tool):** Enable the magic-wand icon in the Label Studio toolbar. Click on any object in the image and SAM generates a precise polygon around it. You can:
- Click individual points to refine the selection
- Draw a rough bounding box and let SAM segment the contents

## 7. Exporting Annotations

After annotating images in Label Studio, export to YOLO and/or COCO format for model training:
```bash
python label_studio/export_annotations.py \
    --project-id 1 \
    --username your@email.com \
    --password yourpwd \
    --format both
```

Exports are saved to:
- `label_studio/exports/yolo/` — YOLO `.txt` files + `classes.txt`
- `label_studio/exports/coco/` — `annotations.json` in COCO format

## 8. Backup and Restore

Create a portable ZIP backup of the database, images, and annotations:
```bash
python export_backup.py --ls-project-id 1 --ls-username you@email.com --ls-password yourpwd
```

Restore or merge into another machine:
```bash
python import_backup.py meteorai_backup_TIMESTAMP.zip --ls-username you@email.com --ls-password yourpwd
```

See [README_EXPORT.md](../README_EXPORT.md) for full documentation.

## Service URLs

| Service        | URL                     | Port |
|----------------|-------------------------|------|
| Streamlit      | http://localhost:8501   | 8501 |
| Label Studio   | http://localhost:8080   | 8080 |
| SAM ML backend | http://localhost:9090   | 9090 |
| PostgreSQL     | localhost               | 5432 |
