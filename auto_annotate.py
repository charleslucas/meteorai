#!/usr/bin/env python3
"""
auto_annotate.py — Run the trained YOLOv8 model on Label Studio tasks and push
predictions as pre-annotations so human reviewers only need to correct, not draw.

Usage:
    # Annotate only tasks that have no human annotations yet (default)
    python auto_annotate.py

    # Annotate ALL tasks (adds/replaces predictions even if human annotation exists)
    python auto_annotate.py --all

    # Annotate specific task IDs
    python auto_annotate.py --task-ids 12 34 56

    # Use a specific model instead of training/best_model.txt
    python auto_annotate.py --model path/to/best.pt

    # Raise the confidence threshold (default 0.25)
    python auto_annotate.py --conf 0.4

    # Dry run — show what would be pushed without actually pushing
    python auto_annotate.py --dry-run

How it works:
    1. Fetch tasks from Label Studio.
    2. Filter to tasks that need predictions (unannotated by default).
    3. Locate each image file on disk via the task's local-files URL.
    4. Run YOLOv8 inference.
    5. POST a Prediction to /api/predictions — Label Studio shows these as
       suggestions the human can accept, tweak, or discard.  They do NOT count
       as human annotations until the reviewer saves them.
"""

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import unquote

import requests

# ---------------------------------------------------------------------------
# Project paths & config
# ---------------------------------------------------------------------------
PROJECT_DIR = Path(__file__).resolve().parent
SCRAPER_DIR = PROJECT_DIR / "meteorite_scraper"
sys.path.insert(0, str(SCRAPER_DIR))

from dotenv import load_dotenv
load_dotenv(SCRAPER_DIR / ".env")

from config import IMAGES_DIR, LABEL_STUDIO_URL, LABEL_STUDIO_API_KEY, LABEL_STUDIO_PROJECT_ID

BEST_MODEL_PTR = PROJECT_DIR / "training" / "best_model.txt"
DEFAULT_MODEL  = PROJECT_DIR / "training" / "runs" / "meteorite_detector" / "weights" / "best.pt"

# Matches the labeling config in Label Studio
LS_FROM_NAME = "bbox"
LS_TO_NAME   = "image"
LS_TYPE      = "rectanglelabels"


# ---------------------------------------------------------------------------
# Label Studio helpers
# ---------------------------------------------------------------------------

def _ls_session():
    s = requests.Session()
    prefix = "Bearer" if LABEL_STUDIO_API_KEY.startswith("eyJ") else "Token"
    s.headers.update({
        "Authorization": f"{prefix} {LABEL_STUDIO_API_KEY}",
        "Content-Type": "application/json",
    })
    return s


def fetch_tasks(session, project_id):
    """Return all tasks in the project (with annotations and predictions inline)."""
    tasks = []
    page = 1
    base = LABEL_STUDIO_URL.rstrip("/")
    while True:
        r = session.get(
            f"{base}/api/tasks",
            params={
                "project": project_id,
                "page": page,
                "page_size": 100,
                "fields": "all",          # include annotations + predictions
            },
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        batch = data.get("tasks", data) if isinstance(data, dict) else data
        if not batch:
            break
        tasks.extend(batch)
        if isinstance(data, dict) and not data.get("next"):
            break
        page += 1
    return tasks


def image_filename_from_task(task):
    """Extract the stored filename from a Label Studio local-files URL."""
    image_url = task.get("data", {}).get("image", "")
    if "?d=" in image_url:
        path = unquote(image_url.split("?d=", 1)[1])
        return Path(path.replace("\\", "/")).name
    # Fallback: last path segment
    return image_url.split("/")[-1] if image_url else None


def delete_existing_predictions(session, task_id):
    """Remove any existing model predictions on a task before adding new ones."""
    base = LABEL_STUDIO_URL.rstrip("/")
    r = session.get(f"{base}/api/predictions", params={"task": task_id}, timeout=10)
    if not r.ok:
        return
    for pred in r.json():
        session.delete(f"{base}/api/predictions/{pred['id']}", timeout=10)


def push_prediction(session, task_id, results, score, model_version, dry_run=False):
    """POST a prediction to Label Studio."""
    payload = {
        "task":          task_id,
        "result":        results,
        "score":         round(float(score), 4),
        "model_version": model_version,
    }
    if dry_run:
        print(f"    [DRY RUN] Would POST prediction: {len(results)} box(es), score={score:.3f}")
        return True

    base = LABEL_STUDIO_URL.rstrip("/")
    r = session.post(f"{base}/api/predictions", json=payload, timeout=15)
    if r.ok:
        return True
    print(f"    ERROR pushing prediction: {r.status_code} {r.text[:200]}")
    return False


# ---------------------------------------------------------------------------
# YOLO inference
# ---------------------------------------------------------------------------

def load_model(model_path):
    try:
        from ultralytics import YOLO
    except ImportError:
        print("ERROR: ultralytics not installed.  Run: pip install ultralytics")
        sys.exit(1)
    model_path = Path(model_path)
    if not model_path.exists():
        print(f"ERROR: Model file not found: {model_path}")
        print("       Train a model first with: python train_model.py")
        sys.exit(1)
    print(f"Loading model: {model_path}")
    return YOLO(str(model_path))


def resolve_model_path(explicit_path):
    if explicit_path:
        return Path(explicit_path)
    if BEST_MODEL_PTR.exists():
        p = Path(BEST_MODEL_PTR.read_text().strip())
        if p.exists():
            return p
        print(f"WARNING: best_model.txt points to {p} which doesn't exist.")
    if DEFAULT_MODEL.exists():
        return DEFAULT_MODEL
    print("ERROR: No trained model found.  Run: python train_model.py")
    sys.exit(1)


def run_inference(model, image_path, conf_threshold):
    """
    Run YOLOv8 on one image and return a list of Label Studio result dicts.
    Returns (results_list, mean_confidence).
    """
    results = model(str(image_path), conf=conf_threshold, verbose=False)
    ls_results = []
    confidences = []

    for r in results:
        if r.boxes is None:
            continue
        orig_w, orig_h = r.orig_shape[1], r.orig_shape[0]

        for box in r.boxes:
            cls_idx   = int(box.cls[0])
            cls_name  = model.names[cls_idx]
            conf      = float(box.conf[0])

            # box.xyxy: [x1, y1, x2, y2] in pixels
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            x_pct = x1 / orig_w * 100.0
            y_pct = y1 / orig_h * 100.0
            w_pct = (x2 - x1) / orig_w * 100.0
            h_pct = (y2 - y1) / orig_h * 100.0

            ls_results.append({
                "from_name": LS_FROM_NAME,
                "to_name":   LS_TO_NAME,
                "type":      LS_TYPE,
                "score":     round(conf, 4),
                "value": {
                    "x":               round(x_pct, 4),
                    "y":               round(y_pct, 4),
                    "width":           round(w_pct, 4),
                    "height":          round(h_pct, 4),
                    "rotation":        0,
                    "rectanglelabels": [cls_name],
                },
            })
            confidences.append(conf)

    mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
    return ls_results, mean_conf


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Auto-annotate Label Studio tasks with YOLOv8.")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--all", action="store_true",
                        help="Run on all tasks, not just unannotated ones.")
    target.add_argument("--task-ids", nargs="+", type=int, metavar="ID",
                        help="Run only on these specific task IDs.")
    parser.add_argument("--model", metavar="PATH",
                        help="Path to .pt model file (default: training/best_model.txt).")
    parser.add_argument("--conf", type=float, default=0.25,
                        help="Confidence threshold for detections (default: 0.25).")
    parser.add_argument("--replace", action="store_true",
                        help="Delete existing predictions before pushing new ones.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would happen without pushing anything.")
    args = parser.parse_args()

    if not LABEL_STUDIO_API_KEY:
        print("ERROR: LABEL_STUDIO_API_KEY not set in .env")
        sys.exit(1)

    # --- Load model ---
    model_path   = resolve_model_path(args.model)
    model        = load_model(model_path)
    model_version = model_path.parent.parent.name  # e.g. "meteorite_detector"
    print(f"Model classes: {model.names}")
    print(f"Model version tag: {model_version}")

    # --- Fetch tasks ---
    session    = _ls_session()
    print(f"\nFetching tasks from {LABEL_STUDIO_URL} project {LABEL_STUDIO_PROJECT_ID}...")
    all_tasks  = fetch_tasks(session, LABEL_STUDIO_PROJECT_ID)
    print(f"Found {len(all_tasks)} tasks total.")

    # --- Filter ---
    if args.task_ids:
        id_set = set(args.task_ids)
        tasks  = [t for t in all_tasks if t["id"] in id_set]
        print(f"Targeting {len(tasks)} task(s) by ID.")
    elif args.all:
        tasks = all_tasks
        print("Targeting all tasks.")
    else:
        # Default: only tasks with no human annotations
        tasks = [t for t in all_tasks if not t.get("annotations")]
        print(f"Targeting {len(tasks)} unannotated task(s).")

    if not tasks:
        print("Nothing to do.")
        return

    # --- Process ---
    ok = skipped = failed = no_image = no_detect = 0

    for task in tasks:
        task_id  = task["id"]
        filename = image_filename_from_task(task)
        if not filename:
            print(f"  Task {task_id}: could not parse image URL, skipping.")
            no_image += 1
            continue

        img_path = Path(IMAGES_DIR) / filename
        if not img_path.exists():
            print(f"  Task {task_id}: image file not found ({filename}), skipping.")
            no_image += 1
            continue

        print(f"  Task {task_id}: {filename}", end="")

        # Replace existing predictions if requested
        if args.replace and not args.dry_run:
            delete_existing_predictions(session, task_id)

        # Run inference
        ls_results, mean_conf = run_inference(model, img_path, args.conf)

        if not ls_results:
            print(f"  → no detections above conf={args.conf}")
            no_detect += 1
            continue

        # Summarise detections
        counts = {}
        for res in ls_results:
            label = res["value"]["rectanglelabels"][0]
            counts[label] = counts.get(label, 0) + 1
        summary = ", ".join(f"{v}×{k}" for k, v in counts.items())
        print(f"  → {len(ls_results)} detection(s): {summary}  (mean conf {mean_conf:.2f})")

        if push_prediction(session, task_id, ls_results, mean_conf, model_version, dry_run=args.dry_run):
            ok += 1
        else:
            failed += 1

    # --- Summary ---
    print(f"""
=== Auto-annotation complete ===
  Predictions pushed:  {ok}
  No detections:       {no_detect}
  Image not found:     {no_image}
  Push errors:         {failed}
  Total tasks:         {len(tasks)}
""")
    if ok and not args.dry_run:
        print(f"Open Label Studio at {LABEL_STUDIO_URL} to review predictions.")


if __name__ == "__main__":
    main()
