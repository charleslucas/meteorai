#!/usr/bin/env python3
"""
train_classifier.py — Train a YOLOv8 image classifier to distinguish
meteorite-in-situ (on the ground, useful) from everything else (studio,
hand, display case — not useful for detector training).

Usage:
    python train_classifier.py

    # Override source directories
    python train_classifier.py \\
        --in-situ-dir  "unsorted_media/meteorites_in_situ" \\
        --other-dir    "unsorted_media/53 Meteorite with background photos"

    # Tune training
    python train_classifier.py --epochs 80 --model yolov8s-cls.pt

The trained model is saved to training/classifier/weights/best.pt and a
pointer written to training/best_classifier.txt so sort_media.py can find it.
"""

import argparse
import random
import shutil
import sys
from pathlib import Path

PROJECT_DIR    = Path(__file__).resolve().parent
SCRAPER_DIR    = PROJECT_DIR / "meteorite_scraper"
CLASSIFIER_DIR = PROJECT_DIR / "training" / "classifier"
DATA_DIR       = PROJECT_DIR / "training" / "classifier_data"

# Default source directories
DEFAULT_IN_SITU = PROJECT_DIR / "unsorted_media" / "meteorites_in_situ"
DEFAULT_OTHER   = PROJECT_DIR / "unsorted_media" / "53 Meteorite with background photos"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif"}

CLASS_IN_SITU = "in_situ"
CLASS_OTHER   = "other"


def collect_images(directory):
    directory = Path(directory)
    if not directory.exists():
        print(f"ERROR: Directory not found: {directory}")
        sys.exit(1)
    imgs = [
        p for p in directory.rglob("*")
        if p.suffix.lower() in IMAGE_EXTS
        and p.is_file()
        and not p.name.startswith(".")   # skip macOS ._resource forks and hidden files
    ]
    return imgs


def build_dataset(in_situ_imgs, other_imgs, val_split=0.2, seed=42):
    """
    Copy images into training/classifier_data/{train,val}/{in_situ,other}/.
    Balances classes by downsampling the larger one to 2× the smaller.
    """
    random.seed(seed)

    # Balance: cap the larger class at 2× the smaller to avoid severe imbalance
    n_min = min(len(in_situ_imgs), len(other_imgs))
    cap   = n_min * 2
    if len(in_situ_imgs) > cap:
        in_situ_imgs = random.sample(in_situ_imgs, cap)
        print(f"  in_situ downsampled to {cap} (was {n_min * 2 + (len(in_situ_imgs) - cap)})")
    if len(other_imgs) > cap:
        other_imgs = random.sample(other_imgs, cap)
        print(f"  other downsampled to {cap}")

    def split(imgs):
        random.shuffle(imgs)
        n_val = max(1, int(len(imgs) * val_split))
        return imgs[n_val:], imgs[:n_val]

    in_situ_train, in_situ_val = split(in_situ_imgs)
    other_train,   other_val   = split(other_imgs)

    print(f"  in_situ : {len(in_situ_train)} train / {len(in_situ_val)} val")
    print(f"  other   : {len(other_train)} train / {len(other_val)} val")

    # Wipe and rebuild
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)

    def copy_batch(imgs, split_name, class_name):
        dest = DATA_DIR / split_name / class_name
        dest.mkdir(parents=True, exist_ok=True)
        for i, src in enumerate(imgs):
            ext = src.suffix.lower()
            shutil.copy2(src, dest / f"{i:05d}{ext}")

    copy_batch(in_situ_train, "train", CLASS_IN_SITU)
    copy_batch(in_situ_val,   "val",   CLASS_IN_SITU)
    copy_batch(other_train,   "train", CLASS_OTHER)
    copy_batch(other_val,     "val",   CLASS_OTHER)

    print(f"  Dataset written to {DATA_DIR}")
    return len(in_situ_train) + len(other_train)


def train(model_name, epochs, batch, imgsz, device):
    try:
        from ultralytics import YOLO
    except ImportError:
        print("ERROR: ultralytics not installed. Run: pip install ultralytics")
        sys.exit(1)

    CLASSIFIER_DIR.mkdir(parents=True, exist_ok=True)
    model   = YOLO(model_name)
    results = model.train(
        data    = str(DATA_DIR),
        epochs  = epochs,
        batch   = batch,
        imgsz   = imgsz,
        device  = device,
        project = str(PROJECT_DIR / "training" / "runs"),
        name    = "meteorite_classifier",
        exist_ok= True,
        patience= 15,
        save    = True,
        plots   = True,
    )
    return results


def report():
    best = PROJECT_DIR / "training" / "runs" / "meteorite_classifier" / "weights" / "best.pt"
    if best.exists():
        print(f"\n  Best model: {best}")
        ptr = PROJECT_DIR / "training" / "best_classifier.txt"
        ptr.write_text(str(best))
        print(f"  Pointer saved to: {ptr}")
    else:
        print("  WARNING: best.pt not found — check training logs.")


def main():
    parser = argparse.ArgumentParser(description="Train in-situ vs other meteorite image classifier.")
    parser.add_argument("--in-situ-dir", default=str(DEFAULT_IN_SITU),
                        help="Directory of in-situ (on-ground) meteorite images.")
    parser.add_argument("--other-dir", default=str(DEFAULT_OTHER),
                        help="Directory of 'other' (studio, hand, etc.) meteorite images.")
    parser.add_argument("--model", default="yolov8s-cls.pt",
                        help="YOLOv8 classification model (default: yolov8s-cls.pt).")
    parser.add_argument("--epochs", type=int, default=60,
                        help="Training epochs (default: 60).")
    parser.add_argument("--batch", type=int, default=-1,
                        help="Batch size; -1 = auto (default: -1).")
    parser.add_argument("--imgsz", type=int, default=224,
                        help="Image size (default: 224).")
    parser.add_argument("--device", default=None,
                        help="Device: 0 for GPU, cpu, or blank for auto.")
    parser.add_argument("--val-split", type=float, default=0.2,
                        help="Validation fraction (default: 0.2).")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    print("=== MeteorAI Scene Classifier Training ===")

    print("\n[1/3] Collecting images...")
    in_situ_imgs = collect_images(args.in_situ_dir)
    other_imgs   = collect_images(args.other_dir)
    print(f"  in_situ source: {len(in_situ_imgs)} images  ({args.in_situ_dir})")
    print(f"  other source:   {len(other_imgs)} images  ({args.other_dir})")

    if len(in_situ_imgs) < 5 or len(other_imgs) < 5:
        print("ERROR: Need at least 5 images per class.")
        sys.exit(1)

    print("\n[2/3] Building dataset...")
    build_dataset(in_situ_imgs, other_imgs, val_split=args.val_split, seed=args.seed)

    print(f"\n[3/3] Training {args.model} for {args.epochs} epochs...")
    train(args.model, args.epochs, args.batch, args.imgsz, args.device)

    report()
    print("\nDone. Run sort_media.py to classify and import images.")


if __name__ == "__main__":
    main()
