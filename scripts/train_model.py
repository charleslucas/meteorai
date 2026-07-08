#!/usr/bin/env python3
"""
train_model.py - Export annotations from Label Studio and train a YOLOv8
detection model on meteorite images.

Usage:
    python train_model.py                        # export + train (default run)
    python train_model.py --skip-export          # use existing exports, just train
    python train_model.py --model yolov8m.pt     # choose model size
    python train_model.py --epochs 100           # override epoch count
    python train_model.py --name in_situ_no_mock --in-situ-only --exclude-mock --exclude-sectioned

Model size guide (pick based on dataset size and GPU memory):
    yolov8n.pt  - nano,   fastest,  ~3M params   (< 100 images)
    yolov8s.pt  - small,  default,  ~11M params  (100-500 images)
    yolov8m.pt  - medium,           ~26M params  (500-2000 images)
    yolov8l.pt  - large,            ~44M params  (2000+ images)

Requirements:
    pip install ultralytics
"""

import argparse
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_DIR  = Path(__file__).resolve().parent.parent
SCRAPER_DIR  = PROJECT_DIR / "meteorite_scraper"
LS_DIR       = PROJECT_DIR / "label_studio"
EXPORTS_DIR  = LS_DIR / "exports" / "yolo"
RUNS_DIR     = PROJECT_DIR / "training" / "runs"

sys.path.insert(0, str(SCRAPER_DIR))
from dotenv import load_dotenv
load_dotenv(SCRAPER_DIR / ".env")
from config import IMAGES_DIR, LABEL_STUDIO_URL, LABEL_STUDIO_API_KEY, LABEL_STUDIO_PROJECT_ID, DB_CONFIG

# ---------------------------------------------------------------------------
# Classes - keep in sync with label_studio/export_annotations.py
# ---------------------------------------------------------------------------
CLASSES = ["meteorite", "fusion_crust", "regmaglypts", "metal_flake", "scale_reference"]

# Minimum annotations per class to include it in training.
MIN_CLASS_EXAMPLES = 5


# ---------------------------------------------------------------------------
# Step 1: Export annotations from Label Studio
# ---------------------------------------------------------------------------

def export_annotations():
    """Re-export YOLO annotations from Label Studio."""
    if not LABEL_STUDIO_API_KEY:
        print("WARNING: LABEL_STUDIO_API_KEY not set - skipping export, using existing files.")
        return

    print("\n[1/4] Exporting annotations from Label Studio...")
    result = subprocess.run([
        sys.executable,
        str(LS_DIR / "export_annotations.py"),
        "--project-id", str(LABEL_STUDIO_PROJECT_ID),
        "--api-key", LABEL_STUDIO_API_KEY,
        "--format", "yolo",
    ], cwd=str(PROJECT_DIR))

    if result.returncode != 0:
        print("WARNING: Export failed - continuing with existing annotation files.")


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_stems_where(condition_sql):
    """Return a set of stored_filename stems matching a SQL WHERE clause."""
    try:
        import psycopg2
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute(f"SELECT stored_filename FROM meteorites WHERE {condition_sql}")
        stems = {Path(row[0]).stem for row in cur.fetchall()}
        cur.close()
        conn.close()
        return stems
    except Exception as exc:
        print(f"  WARNING: DB query failed ({exc}) - filter not applied.")
        return set()


# ---------------------------------------------------------------------------
# Step 2: Build train/val split
# ---------------------------------------------------------------------------

def build_dataset(val_split=0.15, seed=42, exclude_sectioned=False,
                  in_situ_only=False, exclude_mock=False, include_negatives=True,
                  run_name="meteorite_detector"):
    """
    Create training/dataset_<run_name>/ with train/val splits.

    Positive images are filtered by the DB flags; negative samples
    (negative_sample=TRUE) are always included when include_negatives=True.
    Negatives with no annotation file are written with empty label files so
    YOLO treats them as background images.
    """
    dataset_dir = PROJECT_DIR / "training" / f"dataset_{run_name}"
    print(f"\n[2/4] Building train/val dataset split -> {dataset_dir.name} ...")

    # All .txt files from Label Studio export (including empty ones)
    all_ann = sorted(EXPORTS_DIR.glob("*.txt"))
    all_ann = [f for f in all_ann if f.name != "classes.txt"]

    # --- Build allowed stem sets from DB ---
    pos_parts = ["(negative_sample IS NOT TRUE)"]
    if exclude_sectioned:
        pos_parts.append("(sectioned IS NOT TRUE)")
    if in_situ_only:
        pos_parts.append("in_situ = TRUE")
    if exclude_mock:
        pos_parts.append("(mock_meteorite IS NOT TRUE)")
    positive_stems = get_stems_where(" AND ".join(pos_parts))

    negative_stems = get_stems_where("negative_sample = TRUE") if include_negatives else set()

    allowed_stems = positive_stems | negative_stems

    print(f"  Filters: in_situ_only={in_situ_only}, exclude_mock={exclude_mock}, "
          f"exclude_sectioned={exclude_sectioned}, include_negatives={include_negatives}")
    print(f"  Allowed stems: {len(positive_stems)} positive + {len(negative_stems)} negative")

    # Filter export files to allowed stems
    ann_files = [f for f in all_ann if f.stem in allowed_stems]

    # Separate annotated (non-empty) from background-only (empty file)
    nonempty_ann = [f for f in ann_files if f.stat().st_size > 0]
    empty_ann    = [f for f in ann_files if f.stat().st_size == 0]

    # Negatives that have no export file at all -> include as background
    ann_stems = {f.stem for f in ann_files}
    extra_neg_images = []
    for stem in negative_stems:
        if stem not in ann_stems:
            img = _find_image(stem)
            if img:
                extra_neg_images.append(img)

    if not nonempty_ann and not empty_ann and not extra_neg_images:
        print("ERROR: No annotation files found after filtering. Run the export first.")
        sys.exit(1)

    # --- Build paired list: (ann_file_or_None, img_path) ---
    class_counts   = {c: 0 for c in CLASSES}
    paired         = []
    missing_images = []

    for ann_file in nonempty_ann:
        img_path = _find_image(ann_file.stem)
        if img_path is None:
            missing_images.append(ann_file.stem)
            continue
        with open(ann_file) as f:
            for line in f:
                parts = line.strip().split()
                if parts:
                    idx = int(parts[0])
                    if idx < len(CLASSES):
                        class_counts[CLASSES[idx]] += 1
        paired.append((ann_file, img_path))

    for ann_file in empty_ann:
        img_path = _find_image(ann_file.stem)
        if img_path:
            paired.append((None, img_path))

    for img_path in extra_neg_images:
        paired.append((None, img_path))

    if missing_images:
        print(f"  WARNING: {len(missing_images)} annotation file(s) had no matching image - skipped.")

    if not paired:
        print("ERROR: No valid (annotation, image) pairs found.")
        sys.exit(1)

    # Determine which classes have enough examples
    active_classes = [c for c in CLASSES if class_counts[c] >= MIN_CLASS_EXAMPLES]
    excluded_cls   = [c for c in CLASSES if 0 < class_counts[c] < MIN_CLASS_EXAMPLES]
    print(f"  Class counts: { {c: class_counts[c] for c in CLASSES} }")
    print(f"  Training on:  {active_classes}")
    if excluded_cls:
        print(f"  Excluded (too few examples): {excluded_cls}")

    active_idx = {CLASSES.index(c): i for i, c in enumerate(active_classes)}

    # Shuffle and split
    random.seed(seed)
    random.shuffle(paired)
    n_val       = max(1, int(len(paired) * val_split))
    val_pairs   = paired[:n_val]
    train_pairs = paired[n_val:]
    print(f"  Split: {len(train_pairs)} train, {len(val_pairs)} val  ({len(paired)} total)")

    # Build directory structure
    for split in ("train", "val"):
        (dataset_dir / "images" / split).mkdir(parents=True, exist_ok=True)
        (dataset_dir / "labels" / split).mkdir(parents=True, exist_ok=True)

    def _write_split(pairs, split):
        for ann_file, img_path in pairs:
            dest_img = dataset_dir / "images" / split / img_path.name
            shutil.copy2(img_path, dest_img)
            dest_lbl = dataset_dir / "labels" / split / (img_path.stem + ".txt")
            if ann_file is None:
                dest_lbl.write_text("")  # empty label = background image
            else:
                lines_out = []
                with open(ann_file) as f:
                    for line in f:
                        parts = line.strip().split()
                        if not parts:
                            continue
                        orig_idx = int(parts[0])
                        if orig_idx not in active_idx:
                            continue
                        new_idx = active_idx[orig_idx]
                        lines_out.append(f"{new_idx} {' '.join(parts[1:])}")
                with open(dest_lbl, "w") as f:
                    f.write("\n".join(lines_out) + "\n")

    _write_split(train_pairs, "train")
    _write_split(val_pairs, "val")

    yaml_path = dataset_dir / "dataset.yaml"
    with open(yaml_path, "w") as f:
        f.write(f"path: {dataset_dir.as_posix()}\n")
        f.write("train: images/train\n")
        f.write("val:   images/val\n")
        f.write(f"nc: {len(active_classes)}\n")
        f.write(f"names: {active_classes}\n")

    print(f"  Dataset written to {dataset_dir}")
    return yaml_path, active_classes


def _find_image(stem):
    """Find the image file matching an annotation stem name."""
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        candidate = IMAGES_DIR / (stem + ext)
        if candidate.exists():
            return candidate
    bare = Path(stem).name
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        candidate = IMAGES_DIR / (bare + ext)
        if candidate.exists():
            return candidate
    return None


# ---------------------------------------------------------------------------
# Step 3: Train YOLOv8
# ---------------------------------------------------------------------------

def train(yaml_path, model_name, epochs, batch, device, run_name="meteorite_detector"):
    """Train YOLOv8 on the prepared dataset."""
    print(f"\n[3/4] Training {model_name} for {epochs} epochs (run: {run_name})...")
    try:
        from ultralytics import YOLO
    except ImportError:
        print("ERROR: ultralytics not installed. Run: pip install ultralytics")
        sys.exit(1)

    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    model = YOLO(model_name)
    results = model.train(
        data=str(yaml_path),
        epochs=epochs,
        batch=batch,
        imgsz=640,
        device=device,
        project=str(RUNS_DIR),
        name=run_name,
        exist_ok=True,
        patience=20,
        save=True,
        plots=True,
    )
    return results


# ---------------------------------------------------------------------------
# Step 4: Report results
# ---------------------------------------------------------------------------

def report(active_classes, run_name="meteorite_detector"):
    best = RUNS_DIR / run_name / "weights" / "best.pt"
    print(f"\n[4/4] Training complete.")
    if best.exists():
        print(f"  Best model: {best}")
        # Only update the shared pointer for the default run name
        if run_name == "meteorite_detector":
            pointer = PROJECT_DIR / "training" / "best_model.txt"
            pointer.write_text(str(best))
            print(f"  Model path saved to: {pointer}")
        else:
            print(f"  (best_model.txt not updated for named run '{run_name}')")
    else:
        print("  WARNING: best.pt not found - check training logs.")
    print(f"  Classes: {active_classes}")
    print(f"  Runs dir: {RUNS_DIR / run_name}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Train YOLOv8 meteorite detector.")
    parser.add_argument("--skip-export", action="store_true",
                        help="Skip Label Studio export, use existing annotation files.")
    parser.add_argument("--model", default="yolov8s.pt",
                        help="YOLOv8 model variant (default: yolov8s.pt).")
    parser.add_argument("--epochs", type=int, default=100,
                        help="Training epochs (default: 100).")
    parser.add_argument("--batch", type=int, default=-1,
                        help="Batch size; -1 = auto (default: -1).")
    parser.add_argument("--device", default=None,
                        help="Device: 0 for GPU, cpu, or leave blank for auto.")
    parser.add_argument("--val-split", type=float, default=0.15,
                        help="Fraction of data for validation (default: 0.15).")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for train/val split (default: 42).")
    parser.add_argument("--clean", action="store_true",
                        help="Delete existing dataset directory before building.")
    parser.add_argument("--name", default="meteorite_detector",
                        help="Run name; sets output dir and dataset dir (default: meteorite_detector).")
    parser.add_argument("--exclude-sectioned", action="store_true",
                        help="Exclude images marked as 'sectioned' in the database.")
    parser.add_argument("--in-situ-only", action="store_true",
                        help="Only use images marked in_situ=TRUE as positives.")
    parser.add_argument("--exclude-mock", action="store_true",
                        help="Exclude mock meteorite images from positives.")
    parser.add_argument("--no-negatives", action="store_true",
                        help="Exclude negative sample images (included by default).")
    args = parser.parse_args()

    print(f"=== MeteorAI Model Training: {args.name} ===")

    dataset_dir = PROJECT_DIR / "training" / f"dataset_{args.name}"
    if args.clean and dataset_dir.exists():
        print(f"  Removing existing dataset at {dataset_dir}")
        shutil.rmtree(dataset_dir)

    if not args.skip_export:
        export_annotations()

    yaml_path, active_classes = build_dataset(
        val_split=args.val_split,
        seed=args.seed,
        exclude_sectioned=args.exclude_sectioned,
        in_situ_only=args.in_situ_only,
        exclude_mock=args.exclude_mock,
        include_negatives=not args.no_negatives,
        run_name=args.name,
    )
    train(yaml_path, args.model, args.epochs, args.batch, args.device, run_name=args.name)
    report(active_classes, run_name=args.name)


if __name__ == "__main__":
    main()
