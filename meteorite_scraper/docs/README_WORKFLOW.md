# MeteorAI — Annotation & Training Workflow

This document describes the iterative loop for building and improving the
meteorite detection model.

---

## Overview

Two parallel pipelines feed the annotation workflow:

```
Scrape (web)       → push_to_label_studio.py  ─┐
                                                ├→ auto_annotate.py → Label Studio → retrain
Sort media (local) → import_images.py         ─┘
```

Each retraining cycle the detector improves, so predictions require less
correction and you get through new images faster.

---

## Pipeline A: Scraping from the web

```bash
cd meteorite_scraper
python main.py
```

New images land in `meteorite_scraper/images/` and are recorded in the
PostgreSQL database with metadata (meteorite name, type, source URL, etc.).

Push any DB records not yet in Label Studio:

```bash
python meteorite_scraper/push_to_label_studio.py
```

---

## Pipeline B: Sorting a local media directory

Use this when you have a folder of unsorted meteorite photos and want to
pull the useful (in-situ / on-ground) ones into the annotation pipeline.

### Step 1 — Classify and sort

```bash
python sort_media.py                  # sorts unsorted_media/ by default
python sort_media.py --source path/   # or specify a directory
python sort_media.py --dry-run        # preview without copying
python sort_media.py --conf 0.7       # stricter confidence (default 0.6)
```

This runs the scene classifier and **moves** files into two directories:
- `sorted_in_situ/` — meteorite on the ground (useful)
- `sorted_not_in_situ/` — studio, hand, display case, etc. (kept for reference)

Images below the confidence threshold are left in place — review them
manually and drop them into whichever folder is correct.

The following subdirectory inside the source is automatically skipped
(it is classifier training data, not images to be sorted):
- `53 Meteorite with background photos/`

`meteorites_in_situ/` is **not** skipped — those images will be classified
and routed normally, landing in `sorted_in_situ/` for import.

### Step 2 — Review and curate

Open `sorted_in_situ/` and:
- Delete anything that was misclassified
- Add any images you want to include manually (drag in from anywhere)

### Step 3 — Import into the pipeline

```bash
python import_images.py                        # imports sorted_in_situ/ by default
python import_images.py --source path/to/dir   # or any other directory
python import_images.py --dry-run              # preview without writing
python import_images.py --skip-ls              # skip Label Studio push
```

Each image is:
1. Validated (must be a real image, not a resource fork or corrupt file)
2. SHA-256 deduplicated against the database (exact duplicates are skipped)
3. Copied to `meteorite_scraper/images/`
4. Inserted into the database with `image_context = 'in_situ'`
5. Pushed to Label Studio as a new task

You can import from any directory directly — for example if you've added
images to the classifier training set and want them in the pipeline too:

```bash
python import_images.py --source "classifier_training_data/in_situ"
```

### Retraining the scene classifier

As you curate more in-situ examples, retrain the classifier to improve
sorting accuracy:

```bash
python train_classifier.py
```

Source directories (configurable via flags):
- `--in-situ-dir`  defaults to `classifier_training_data/in_situ/`
- `--other-dir`    defaults to `classifier_training_data/other/`

`classifier_training_data/` is the permanent home for classifier training
images (gitignored — images stay on disk but aren't tracked in the repo).
Add new curated examples there to improve the classifier over time.

---

## Phase 3: Auto-annotate new tasks

After either pipeline adds new tasks to Label Studio, push detector
predictions to them:

```bash
python auto_annotate.py                  # unannotated tasks only (default)
python auto_annotate.py --all --replace  # refresh predictions on all tasks
python auto_annotate.py --conf 0.4       # raise confidence threshold (default 0.25)
python auto_annotate.py --containment 0.5 # stricter spatial filtering (default 0.3)
python auto_annotate.py --dry-run        # preview without pushing
```

Predictions are yellow suggestion boxes visible in Label Studio. They do
not count as annotations and are never used for training directly.

### Containment filtering

`fusion_crust`, `regmaglypts`, and `metal_flake` cannot exist without a
meteorite. Any detection of these classes that doesn't overlap a `meteorite`
box by at least 30% of its own area is dropped before pushing to Label Studio.
`scale_reference` is independent and is never filtered.

---

## Phase 4: Human review in Label Studio

Open Label Studio at http://localhost:8081

For each new task:

1. Open the task
2. Load the prediction as your starting point (lightning bolt / Predictions
   panel) — this copies the model's boxes into the editor
3. Fix what's wrong: delete bad boxes, resize off-target ones, add missing ones
4. Hit **Submit** — this saves a human annotation

**Predictions vs. annotations:**
- `auto_annotate.py` only ever writes predictions (`/api/predictions`)
- `train_model.py` only ever reads human annotations (`/api/annotations`)
- `auto_annotate.py --replace` is always safe — it never touches saved annotations

If you already have a correct human annotation on a task, ignore the
prediction — it's just decorative and has no effect on training.

---

## Phase 5: Retrain the detector

Once you have a meaningful batch of new annotations:

```bash
# Fresh export from Label Studio + full retrain
python train_model.py --epochs 150 --model yolov8s.pt --clean

# Skip re-export if annotations haven't changed
python train_model.py --skip-export --epochs 150 --model yolov8s.pt --clean
```

Model size guide:

| Model | Params | Good for |
|---|---|---|
| `yolov8n.pt` | ~3M | < 100 images |
| `yolov8s.pt` | ~11M | 100–500 images ← current default |
| `yolov8m.pt` | ~26M | 500–2000 images |
| `yolov8l.pt` | ~44M | 2000+ images |

The best model is saved to `training/runs/meteorite_detector/weights/best.pt`
and a pointer written to `training/best_model.txt` (gitignored).

After retraining, push fresh predictions:

```bash
python auto_annotate.py --all --replace
```

---

## Annotation classes

| Class | Notes |
|---|---|
| `meteorite` | The whole meteorite — always required |
| `fusion_crust` | Dark glassy exterior — must be within a meteorite box |
| `regmaglypts` | Thumbprint depressions — must be within a meteorite box |
| `metal_flake` | Shiny metal inclusions — must be within a meteorite box |
| `scale_reference` | Ruler or coin for scale — independent |

Classes need ≥ 5 annotated examples to be included in training
(`MIN_CLASS_EXAMPLES` in `train_model.py`). Currently `regmaglypts` (1) and
`metal_flake` (0) are excluded — annotate more to unlock them.

---

## Tips

- **Prediction mostly right:** load it, nudge boxes, delete bad ones, submit.
  Much faster than drawing from scratch.
- **Lots of junk boxes:** the containment filter removes the worst offenders.
  Load, clean up the rest, submit.
- **All boxes wrong:** annotate from scratch.
- **Already-annotated tasks:** don't bother fixing the prediction — the human
  annotation is what gets used for training.
- **Low-confidence sort results:** `sort_media.py` moves high-confidence
  images out; whatever remains in the source is exactly the uncertain ones.
  Review them manually and move into `sorted_in_situ/` or
  `sorted_not_in_situ/` as appropriate.
