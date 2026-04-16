# MeteorAI — Annotation & Training Workflow

This document describes the iterative loop for building and improving the
meteorite detection model.

---

## Overview

The loop has four phases that repeat as more data is collected:

```
Scrape → Auto-annotate → Human review → Retrain → (repeat)
```

Each cycle the model improves, so predictions require less correction and
you get through new images faster.

---

## Phase 1: Scrape new images

```bash
cd meteorite_scraper
python main.py
```

New images land in `meteorite_scraper/images/` and are recorded in the
PostgreSQL database with metadata (meteorite name, type, source URL, etc.).

After scraping, push new images to Label Studio:

```bash
python meteorite_scraper/push_to_label_studio.py
```

This creates new tasks in Label Studio for any DB records not already there.

---

## Phase 2: Auto-annotate new tasks

Run the trained model against tasks that have no human annotation yet:

```bash
python auto_annotate.py
```

This pushes **predictions** (yellow suggestion boxes) to each unannotated
task. Predictions are a starting point for human review — they do not count
as annotations and are never used for training directly.

Useful flags:
```bash
python auto_annotate.py --conf 0.4        # raise confidence threshold (default 0.25)
python auto_annotate.py --all --replace   # refresh predictions on all tasks
python auto_annotate.py --dry-run         # preview without pushing
python auto_annotate.py --containment 0.5 # stricter spatial filtering (default 0.3)
```

### How containment filtering works

`fusion_crust`, `regmaglypts`, and `metal_flake` cannot physically exist
without a meteorite. The script enforces this: any detection of these classes
that doesn't overlap a `meteorite` box by at least 30% of its own area is
automatically dropped before the prediction is pushed to Label Studio.
`scale_reference` is independent and is not filtered.

---

## Phase 3: Human review in Label Studio

Open Label Studio at http://localhost:8081

For each new task:

1. Open the task
2. Load the prediction as your starting point (lightning bolt / Predictions
   panel in the annotation UI) — this copies the model's boxes into the editor
3. Fix what's wrong:
   - Delete incorrect boxes
   - Resize or move boxes that are off
   - Add any boxes the model missed
4. Hit **Submit** — this saves a human annotation

**Important:** predictions and human annotations are completely separate.
- `auto_annotate.py` only ever writes to predictions (`/api/predictions`)
- `train_model.py` only ever reads from human annotations (`/api/annotations`)
- Running `auto_annotate.py --replace` is safe — it only updates predictions,
  never touches your saved annotations

If you already have a correct human annotation on a task, you can ignore the
prediction entirely — it's just a visual layer and has no effect on training.

---

## Phase 4: Retrain

Once you have a meaningful batch of new annotations:

```bash
# Fresh export from Label Studio + full retrain
python train_model.py --epochs 150 --model yolov8s.pt --clean

# Or skip re-export if you just want to retrain on existing exports
python train_model.py --skip-export --epochs 150 --model yolov8s.pt --clean
```

Model size guide (pick based on dataset size):

| Model | Params | Good for |
|---|---|---|
| `yolov8n.pt` | ~3M | < 100 images |
| `yolov8s.pt` | ~11M | 100–500 images ← current default |
| `yolov8m.pt` | ~26M | 500–2000 images |
| `yolov8l.pt` | ~44M | 2000+ images |

The best model is saved to `training/runs/meteorite_detector/weights/best.pt`
and a pointer written to `training/best_model.txt` (gitignored).

After retraining, push fresh predictions to Label Studio:

```bash
python auto_annotate.py --all --replace
```

---

## Current annotation classes

| Class | Notes |
|---|---|
| `meteorite` | The whole meteorite — always required |
| `fusion_crust` | Dark glassy exterior — must be within a meteorite box |
| `regmaglypts` | Thumbprint depressions — must be within a meteorite box |
| `metal_flake` | Shiny metal inclusions — must be within a meteorite box |
| `scale_reference` | Ruler or coin for scale — independent |

Classes need a minimum of 5 annotated examples before they are included in
training (configurable via `MIN_CLASS_EXAMPLES` in `train_model.py`).
Currently `regmaglypts` (1 example) and `metal_flake` (0 examples) are
excluded — annotate more to unlock them.

---

## Tips

- **For tasks where the prediction is mostly right:** load it, nudge any
  off-target boxes, delete the bad ones, submit. Much faster than drawing
  from scratch.
- **For tasks with many junk boxes:** the containment filter already removes
  the worst offenders. Load, clean up the rest, submit.
- **For tasks with no prediction or all boxes wrong:** annotate from scratch.
- **Don't fix predictions on already-annotated tasks** — the human annotation
  is already correct and is what gets used for training. The prediction on
  those tasks is just decorative.
