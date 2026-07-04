#!/usr/bin/env python3
"""
auto_annotate.py â€” Run the trained YOLOv8 model on Label Studio tasks and push
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

    # Dry run â€” show what would be pushed without actually pushing
    python auto_annotate.py --dry-run

How it works:
    1. Fetch tasks from Label Studio.
    2. Filter to tasks that need predictions (unannotated by default).
    3. Locate each image file on disk via the task's local-files URL.
    4. Run YOLOv8 inference.
    5. POST a Prediction to /api/predictions â€” Label Studio shows these as
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
PROJECT_DIR  = Path(__file__).resolve().parent.parent
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
    page_size = 100
    base = LABEL_STUDIO_URL.rstrip("/")
    while True:
        r = session.get(
            f"{base}/api/tasks",
            params={
                "project": project_id,
                "page": page,
                "page_size": page_size,
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
        # Stop when we get a partial page (last page) or no "next" URL
        if len(batch) < page_size:
            break
        if isinstance(data, dict) and data.get("next") is None and "next" in data:
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
# Containment filtering
# ---------------------------------------------------------------------------

# Classes that must be spatially contained within a parent class box.
# Detections of these classes are dropped if they don't overlap sufficiently
# with at least one box of their required parent class.
CONTAINMENT_RULES = {
    # child_class      : parent_class
    "fusion_crust"     : "meteorite",
    "regmaglypts"      : "meteorite",
    "metal_flake"      : "meteorite",
}


def _containment_ratio(child, parent):
    """
    Fraction of child box covered by parent box (0.0 â€“ 1.0).
    Boxes are (x1, y1, x2, y2) in any consistent unit.
    """
    ix1 = max(child[0], parent[0])
    iy1 = max(child[1], parent[1])
    ix2 = min(child[2], parent[2])
    iy2 = min(child[3], parent[3])
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    intersection = (ix2 - ix1) * (iy2 - iy1)
    child_area   = (child[2] - child[0]) * (child[3] - child[1])
    return intersection / child_area if child_area > 0 else 0.0


def apply_containment_filter(detections, threshold=0.3):
    """
    Remove sub-meteorite detections that don't sit inside a meteorite box.

    Args:
        detections: list of dicts with keys 'cls', 'conf', 'xyxy' (pixel coords)
        threshold:  minimum containment ratio to keep a child detection

    Returns:
        filtered list, number of boxes dropped
    """
    # Index parent boxes by class name
    parent_boxes = {}
    for det in detections:
        cls = det["cls"]
        if cls in CONTAINMENT_RULES.values():
            parent_boxes.setdefault(cls, []).append(det["xyxy"])

    kept    = []
    dropped = 0
    for det in detections:
        required_parent = CONTAINMENT_RULES.get(det["cls"])
        if required_parent is None:
            kept.append(det)
            continue
        parents = parent_boxes.get(required_parent, [])
        if not parents:
            # No parent boxes in this image at all â€” drop the child
            dropped += 1
            continue
        best = max(_containment_ratio(det["xyxy"], p) for p in parents)
        if best >= threshold:
            kept.append(det)
        else:
            dropped += 1

    return kept, dropped


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


def run_inference(model, image_path, conf_threshold, containment_threshold=0.3):
    """
    Run YOLOv8 on one image and return a list of Label Studio result dicts.

    Sub-meteorite classes (fusion_crust, regmaglypts, metal_flake) are dropped
    if they don't overlap sufficiently with a meteorite box â€” enforcing the
    real-world constraint that fusion crust can't exist without a meteorite.

    Returns (results_list, mean_confidence, n_dropped).
    """
    results  = model(str(image_path), conf=conf_threshold, verbose=False)
    raw_dets = []

    for r in results:
        if r.boxes is None:
            continue
        orig_w, orig_h = r.orig_shape[1], r.orig_shape[0]

        for box in r.boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            raw_dets.append({
                "cls":  model.names[int(box.cls[0])],
                "conf": float(box.conf[0]),
                "xyxy": (x1, y1, x2, y2),
                "orig_w": orig_w,
                "orig_h": orig_h,
            })

    # Apply spatial containment constraint
    filtered, n_dropped = apply_containment_filter(raw_dets, threshold=containment_threshold)

    # Convert to Label Studio format
    ls_results  = []
    confidences = []
    for det in filtered:
        orig_w, orig_h = det["orig_w"], det["orig_h"]
        x1, y1, x2, y2 = det["xyxy"]
        ls_results.append({
            "from_name": LS_FROM_NAME,
            "to_name":   LS_TO_NAME,
            "type":      LS_TYPE,
            "score":     round(det["conf"], 4),
            "value": {
                "x":               round(x1 / orig_w * 100.0, 4),
                "y":               round(y1 / orig_h * 100.0, 4),
                "width":           round((x2 - x1) / orig_w * 100.0, 4),
                "height":          round((y2 - y1) / orig_h * 100.0, 4),
                "rotation":        0,
                "rectanglelabels": [det["cls"]],
            },
        })
        confidences.append(det["conf"])

    mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
    return ls_results, mean_conf, n_dropped


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
    parser.add_argument("--containment", type=float, default=0.3,
                        help="Min fraction of a sub-meteorite box that must overlap a meteorite "
                             "box to be kept (default: 0.3). Set to 0 to disable.")
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
    total_dropped = 0

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

        # Run inference with containment filtering
        ls_results, mean_conf, n_dropped = run_inference(
            model, img_path, args.conf,
            containment_threshold=args.containment,
        )
        total_dropped += n_dropped

        if not ls_results:
            suffix = f"  (dropped {n_dropped} orphan sub-meteorite box(es))" if n_dropped else ""
            print(f"  â†’ no detections above conf={args.conf}{suffix}")
            no_detect += 1
            continue

        # Summarise detections
        counts = {}
        for res in ls_results:
            label = res["value"]["rectanglelabels"][0]
            counts[label] = counts.get(label, 0) + 1
        summary = ", ".join(f"{v}Ã—{k}" for k, v in counts.items())
        drop_note = f"  [{n_dropped} dropped]" if n_dropped else ""
        print(f"  â†’ {len(ls_results)} detection(s): {summary}  (mean conf {mean_conf:.2f}){drop_note}")

        if push_prediction(session, task_id, ls_results, mean_conf, model_version, dry_run=args.dry_run):
            ok += 1
        else:
            failed += 1

    # --- Summary ---
    print(f"""
=== Auto-annotation complete ===
  Predictions pushed:       {ok}
  No detections:            {no_detect}
  Image not found:          {no_image}
  Push errors:              {failed}
  Orphan boxes filtered:    {total_dropped}
  Total tasks:              {len(tasks)}
""")
    if ok and not args.dry_run:
        print(f"Open Label Studio at {LABEL_STUDIO_URL} to review predictions.")


if __name__ == "__main__":
    main()
