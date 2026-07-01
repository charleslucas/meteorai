# Label Studio Guide

Label Studio runs on port 8080 and is the annotation tool for drawing bounding boxes and polygons on meteorite images for model training.

See [SETUP.md](SETUP.md) for installation and startup instructions.

---

## First-Time Setup

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

**Available labels:** `meteorite`, `fusion_crust`, `regmaglypts`, `metal_flake`, `scale_reference`

---

## Keeping Label Studio in Sync

### Automatic push (normal workflow)

Once `LABEL_STUDIO_API_KEY` and `LABEL_STUDIO_PROJECT_ID` are set in `.env`, any image added through the Streamlit app â€” whether from a URL, a local file path, or a YouTube video frame â€” is pushed to Label Studio immediately as a new task. No manual action needed.

### Bulk push (catch-up sync)

If images were added outside the Streamlit app (e.g. via the scraper or direct DB inserts), or if Label Studio was unreachable when an image was imported, use the bulk push script to sync the gap:

```bash
cd meteorite_scraper
python push_to_label_studio.py --dry-run   # preview what's missing
python push_to_label_studio.py             # push only records not in LS
python push_to_label_studio.py --all       # re-push every record
```

The script fetches all existing Label Studio task `image_id` values and only pushes DB records that aren't already there, so it is safe to re-run at any time without creating duplicates.

### Patching task metadata

If tasks exist in Label Studio but are missing metadata fields (e.g. `meteorite_name`, `image_id`), patch them from the database:

```bash
python label_studio/sync_task_metadata.py --api-key YOUR_LEGACY_TOKEN --project-id 2
```

---

## SAM ML Backend (Auto-Annotation)

The SAM (Segment Anything Model) backend lets Label Studio automatically suggest annotations, dramatically speeding up the labeling process.

### Installation

See the **SAM ML Backend** section in [SETUP.md](SETUP.md) for full installation instructions including platform-specific PyTorch/CUDA setup and weight downloads.

Quick summary:
```bash
# Download default model weights (~46 MB)
python label_studio/download_sam_weights.py

# Other sizes
python label_studio/download_sam_weights.py --model tiny   # fastest, ~39 MB
python label_studio/download_sam_weights.py --model large  # most accurate, ~224 MB
```

### Starting the SAM backend

Starts automatically via the main service script:
```powershell
.\start_services.ps1
```

Or standalone:
```cmd
python label_studio\sam_backend.py --port 9090
```

### Connecting to Label Studio

1. Open Label Studio â†’ **Settings â†’ Model â†’ Connect Model**
2. Enter URL: `http://localhost:9090`
3. Enable **"Interactive preannotations"**
4. Click **Validate and Save**

### Annotation modes

**Automatic:** When you open an unannotated image, SAM pre-fills a polygon and bounding box around the most prominent subject. Review and correct as needed.

**Interactive (Smart tool):** Enable the magic-wand icon in the toolbar. Click any object and SAM generates a precise polygon. You can click points to refine or draw a rough bounding box for SAM to segment.

---

## Exporting Annotations

After annotating, export to YOLO and/or COCO format for model training:

```bash
python label_studio/export_annotations.py \
    --project-id 2 \
    --username your@email.com \
    --password yourpwd \
    --format both
```

Exports are saved to:
- `label_studio/exports/yolo/` â€” YOLO `.txt` files + `classes.txt`
- `label_studio/exports/coco/` â€” `annotations.json` in COCO format
