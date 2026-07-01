# MeteorAI â€” Project Progress & Next Steps

Last updated: 2026-04-12

---

## What this project does

End-to-end pipeline for:
1. **Scraping** meteorite images from the Meteoritical Bulletin and other sources
2. **Storing** them in PostgreSQL with metadata, deduped by SHA-256 hash
3. **Annotating** them in Label Studio (bounding boxes + polygons)
4. **Training** a YOLOv8 detection model on the annotations
5. **Auto-annotating** new images with the trained model (active learning loop)
6. **Sorting** a directory of unsorted meteorite images into useful vs. not useful (future)

The Streamlit app (`meteorite_scraper/app.py`) is the main UI for browsing,
importing images, and managing the pipeline.

---

## Current state (April 12, 2026)

### Data
- **86 images** in PostgreSQL, all files present on disk (`meteorite_scraper/images/`)
- **84/86 tasks annotated** in Label Studio (project ID 2, port 8081)
- Annotation classes: `meteorite` (93 boxes), `fusion_crust` (76), `scale_reference` (7),
  `regmaglypts` (1 â€” too few to train), `metal_flake` (0)
- `image_context`, `background_type`, `primary_type` are mostly NULL in the DB â€”
  the scraper wasn't populating these fields well from the Meteoritical Bulletin

### Services
| Service | How to start | Port |
|---|---|---|
| Label Studio | `start_label_studio.bat` | 8081 |
| SAM backend (auto-segment) | `label_studio/start_sam_backend.bat` | 8082 |
| Streamlit app | `cd meteorite_scraper && streamlit run app.py` | 8501 |

All service config (URL, API key, project ID) lives in `meteorite_scraper/.env`.

### Scripts in place

| Script | Purpose |
|---|---|
| `train_model.py` | Export annotations â†’ YOLO dataset split â†’ train YOLOv8 â†’ save `best.pt` |
| `auto_annotate.py` | Load trained model â†’ fetch LS tasks â†’ run inference â†’ push predictions |
| `meteorite_scraper/push_to_label_studio.py` | Bulk-push DB records missing from Label Studio |
| `label_studio/export_annotations.py` | Export LS annotations to YOLO + COCO formats |
| `label_studio/sync_task_metadata.py` | Patch LS tasks missing DB metadata fields |
| `meteorite_scraper/label_studio_client.py` | Push individual tasks from Streamlit |
| `label_studio/fix_task_urls.py` | Fix broken image URLs in LS tasks |

### Docs
All docs are in `docs/`:
- `SETUP.md` â€” environment setup
- `LABEL_STUDIO.md` â€” Label Studio setup, sync, SAM, export
- `EXPORT.md` â€” annotation export workflow
- `TRAINING.md` â€” model training guide

---

## Iterative training loop (how to use it)

```bash
# 1. Train on current annotations (~10 min on RTX 5070 Ti)
python train_model.py --epochs 100 --model yolov8s.pt

# 2. Push predictions to Label Studio for human review
python auto_annotate.py                  # unannotated tasks only (default)
python auto_annotate.py --all --replace  # refresh all predictions

# 3. Correct predictions in Label Studio, then retrain
python train_model.py --epochs 100       # model improves each cycle

# Options for auto_annotate.py:
#   --conf 0.4          raise confidence threshold (default 0.25)
#   --task-ids 1 2 3    specific tasks only
#   --dry-run           preview without pushing
#   --replace           delete old predictions before pushing new ones
```

The model is saved to `training/runs/meteorite_detector/weights/best.pt`
and a pointer written to `training/best_model.txt` (gitignored â€” machine-local path).

---

## Next steps (priority order)

### 1. Proper training run
The pipeline is verified working but only tested with 1 epoch (untrained model).
Run a real training session:
```bash
python train_model.py --epochs 100 --model yolov8s.pt --clean
```
Then run `auto_annotate.py --all` and check predictions look reasonable in Label Studio.

### 2. Image sorter / classifier
Goal: take a directory of unsorted raw meteorite images and classify each as:
- **in-situ / on-ground** â€” useful for detector training
- **studio set** â€” meteorite on white/black table with bright lights, not useful

**Blocker:** `image_context` is NULL for almost all 86 DB images. Need to either:
- Manually tag ~30-50 images as `in_situ` vs `studio` in the Streamlit app, OR
- Write a script that queries the Label Studio annotations + image metadata
  to infer context (images with `scale_reference` boxes are probably studio shots)

Once labeled examples exist, train a YOLOv8 classification model:
```bash
# (future) python train_classifier.py --task sort --classes in_situ studio
```

### 3. Scrape more data
Only 86 images so far â€” detector training will improve significantly with 500+.
The Meteoritical Bulletin scraper (`meteorite_scraper/scraper.py`) is working
but needs to be run more aggressively. Current images are mostly "Drelow" and
"Ozerki" falls â€” need more variety for a robust detector.

```bash
cd meteorite_scraper && python main.py   # run the full scraper
```

After scraping, push new images to Label Studio:
```bash
python meteorite_scraper/push_to_label_studio.py
```

### 4. Streamlit UI integration
Add a "Train & Classify" tab to `meteorite_scraper/app.py` with:
- One-click training kick-off (calls `train_model.py` as a subprocess)
- Show current annotation counts and model performance metrics
- Point at a directory â†’ run the sorter â†’ show results with images

### 5. Export / inference on new images
Once the model is trained well enough, write an inference script that:
- Takes a directory of unsorted images
- Outputs a CSV / moves files into subdirectories by predicted class
- This is the end-goal "sort my hard drive" use case

---

## Known issues / gotchas

- **`image_context` not populated** â€” the Meteoritical Bulletin scraper doesn't
  reliably extract context from the bulletin pages; most records have NULL here.
- **`regmaglypts` and `metal_flake`** need more annotated examples before they
  can be trained (currently 1 and 0 respectively).
- **Label Studio port is 8081**, not the default 8080 â€” all configs updated but
  watch out if spinning up a fresh instance.
- **Windows paths** â€” `best_model.txt` contains an absolute Windows path; don't
  commit it (it's gitignored). Other scripts use `Path(__file__).resolve()` and
  work cross-platform.
- **Merge conflict artifacts** (`app_BACKUP_984.py` etc.) are in the working dir
  but gitignored â€” safe to delete manually if they're cluttering things.
