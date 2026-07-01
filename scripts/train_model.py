#!/usr/bin/env python3
"""
train_model.py â€” Export annotations from Label Studio and train a YOLOv8
detection model on meteorite images.

Usage:
    python train_model.py                        # export + train
    python train_model.py --skip-export          # use existing exports, just train
    python train_model.py --model yolov8s.pt     # choose model size
    python train_model.py --epochs 100           # override epoch count

Model size guide (pick based on dataset size and GPU memory):
    yolov8n.pt  â€” nano,   fastest,  ~3M params   (< 100 images)
    yolov8s.pt  â€” small,  default,  ~11M params  (100â€“500 images)
    yolov8m.pt  â€” medium,           ~26M params  (500â€“2000 images)
    yolov8l.pt  â€” large,            ~44M params  (2000+ images)

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
DATASET_DIR  = PROJECT_DIR / "training" / "dataset"
RUNS_DIR     = PROJECT_DIR / "training" / "runs"

sys.path.insert(0, str(SCRAPER_DIR))
from dotenv import load_dotenv
load_dotenv(SCRAPER_DIR / ".env")
from config import IMAGES_DIR, LABEL_STUDIO_URL, LABEL_STUDIO_API_KEY, LABEL_STUDIO_PROJECT_ID

# ---------------------------------------------------------------------------
# Classes â€” keep in sync with label_studio/export_annotations.py
# ---------------------------------------------------------------------------
CLASSES = ["meteorite", "fusion_crust", "regmaglypts", "metal_flake", "scale_reference"]

# Minimum annotations per class to include it in training.
# Classes below this threshold are excluded (too few examples).
MIN_CLASS_EXAMPLES = 5


# ---------------------------------------------------------------------------
# Step 1: Export annotations from Label Studio
# ---------------------------------------------------------------------------

def export_annotations():
    """Re-export YOLO annotations from Label Studio."""
    if not LABEL_STUDIO_API_KEY:
        print("WARNING: LABEL_STUDIO_API_KEY not set â€” skipping export, using existing files.")
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
        print("WARNING: Export failed â€” continuing with existing annotation files.")


# ---------------------------------------------------------------------------
# Step 2: Build train/val split
# ---------------------------------------------------------------------------

def build_dataset(val_split=0.15, seed=42):
    """
    Create training/dataset/ with the following structure:
        dataset/
            images/
                train/   â† symlinks or copies of image files
                val/
            labels/
                train/   â† YOLO .txt annotation files
                val/
            dataset.yaml
    """
    print("\n[2/4] Building train/val dataset split...")

    # Collect annotation files that have at least one valid label line
    ann_files = sorted(EXPORTS_DIR.glob("*.txt"))
    ann_files = [f for f in ann_files if f.name != "classes.txt" and f.stat().st_size > 0]

    if not ann_files:
        print("ERROR: No annotation files found in", EXPORTS_DIR)
        print("       Run the export first or check Label Studio annotations.")
        sys.exit(1)

    # Count class occurrences to decide which classes to train on
    class_counts = {c: 0 for c in CLASSES}
    paired = []  # (ann_file, image_path) pairs
    missing_images = []

    for ann_file in ann_files:
        # Resolve corresponding image file
        img_path = _find_image(ann_file.stem)
        if img_path is None:
            missing_images.append(ann_file.stem)
            continue

        with open(ann_file) as f:
            lines = [l.strip() for l in f if l.strip()]
        if not lines:
            continue

        for line in lines:
            parts = line.split()
            if parts:
                idx = int(parts[0])
                if idx < len(CLASSES):
                    class_counts[CLASSES[idx]] += 1

        paired.append((ann_file, img_path))

    if missing_images:
        print(f"  WARNING: {len(missing_images)} annotation file(s) had no matching image â€” skipped.")

    if not paired:
        print("ERROR: No valid (annotation, image) pairs found.")
        sys.exit(1)

    # Determine which classes have enough examples
    active_classes = [c for c in CLASSES if class_counts[c] >= MIN_CLASS_EXAMPLES]
    excluded = [c for c in CLASSES if 0 < class_counts[c] < MIN_CLASS_EXAMPLES]
    print(f"  Class counts: { {c: class_counts[c] for c in CLASSES} }")
    print(f"  Training on:  {active_classes}")
    if excluded:
        print(f"  Excluded (too few examples): {excluded}")

    # Build class index remapping (active classes only, 0-indexed)
    active_idx = {CLASSES.index(c): i for i, c in enumerate(active_classes)}

    # Shuffle and split
    random.seed(seed)
    random.shuffle(paired)
    n_val = max(1, int(len(paired) * val_split))
    val_pairs  = paired[:n_val]
    train_pairs = paired[n_val:]
    print(f"  Split: {len(train_pairs)} train, {len(val_pairs)} val  ({len(paired)} total)")

    # Build directory structure
    for split in ("train", "val"):
        (DATASET_DIR / "images" / split).mkdir(parents=True, exist_ok=True)
        (DATASET_DIR / "labels" / split).mkdir(parents=True, exist_ok=True)

    def _write_split(pairs, split):
        written = 0
        for ann_file, img_path in pairs:
            # Copy image
            dest_img = DATASET_DIR / "images" / split / img_path.name
            shutil.copy2(img_path, dest_img)

            # Rewrite annotation with remapped class indices
            dest_lbl = DATASET_DIR / "labels" / split / (img_path.stem + ".txt")
            lines_out = []
            with open(ann_file) as f:
                for line in f:
                    parts = line.strip().split()
                    if not parts:
                        continue
                    orig_idx = int(parts[0])
                    if orig_idx not in active_idx:
                        continue  # skip excluded classes
                    new_idx = active_idx[orig_idx]
                    lines_out.append(f"{new_idx} {' '.join(parts[1:])}")
            if lines_out:
                with open(dest_lbl, "w") as f:
                    f.write("\n".join(lines_out) + "\n")
                written += 1
        return written

    _write_split(train_pairs, "train")
    _write_split(val_pairs, "val")

    # Write dataset.yaml
    yaml_path = DATASET_DIR / "dataset.yaml"
    with open(yaml_path, "w") as f:
        f.write(f"path: {DATASET_DIR.as_posix()}\n")
        f.write("train: images/train\n")
        f.write("val:   images/val\n")
        f.write(f"nc: {len(active_classes)}\n")
        f.write(f"names: {active_classes}\n")

    print(f"  Dataset written to {DATASET_DIR}")
    print(f"  Config: {yaml_path}")
    return yaml_path, active_classes


def _find_image(stem):
    """Find the image file matching an annotation stem name."""
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        candidate = IMAGES_DIR / (stem + ext)
        if candidate.exists():
            return candidate
    # Some filenames may have the images/ prefix in the stem
    bare = Path(stem).name
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        candidate = IMAGES_DIR / (bare + ext)
        if candidate.exists():
            return candidate
    return None


# ---------------------------------------------------------------------------
# Step 3: Train YOLOv8
# ---------------------------------------------------------------------------

def train(yaml_path, model_name, epochs, batch, device):
    """Train YOLOv8 on the prepared dataset."""
    print(f"\n[3/4] Training {model_name} for {epochs} epochs...")
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
        name="meteorite_detector",
        exist_ok=True,
        patience=20,          # early stopping
        save=True,
        plots=True,
    )
    return results


# ---------------------------------------------------------------------------
# Step 4: Report results and save best model path
# ---------------------------------------------------------------------------

def report(active_classes):
    best = RUNS_DIR / "meteorite_detector" / "weights" / "best.pt"
    print(f"\n[4/4] Training complete.")
    if best.exists():
        print(f"  Best model: {best}")
        # Write a pointer file so other scripts can find the latest model
        pointer = PROJECT_DIR / "training" / "best_model.txt"
        pointer.write_text(str(best))
        print(f"  Model path saved to: {pointer}")
    else:
        print("  WARNING: best.pt not found â€” check training logs.")
    print(f"  Classes: {active_classes}")
    print(f"  Runs dir: {RUNS_DIR / 'meteorite_detector'}")


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
    args = parser.parse_args()

    print("=== MeteorAI Model Training ===")

    if args.clean and DATASET_DIR.exists():
        print(f"  Removing existing dataset at {DATASET_DIR}")
        shutil.rmtree(DATASET_DIR)

    if not args.skip_export:
        export_annotations()

    yaml_path, active_classes = build_dataset(val_split=args.val_split, seed=args.seed)
    train(yaml_path, args.model, args.epochs, args.batch, args.device)
    report(active_classes)


if __name__ == "__main__":
    main()
