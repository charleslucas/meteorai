#!/usr/bin/env python3
"""
sort_media.py — Classify images in a directory as in-situ (useful) or other,
and copy them into sorted output directories for manual review before import.

  in_situ  → sorted_in_situ/      (review, then run import_images.py)
  other    → sorted_not_in_situ/  (keep for reference, not imported)

Images are moved, not copied. Whatever remains in the source directory
after a run is exactly the low-confidence images that need manual review —
drop them into sorted_in_situ/ or sorted_not_in_situ/ as appropriate.

Usage:
    python sort_media.py                          # sort all of unsorted_media/
    python sort_media.py --source path/to/dir     # sort a specific directory
    python sort_media.py --dry-run                # preview without copying anything
    python sort_media.py --conf 0.7               # stricter confidence (default 0.6)

After sorting, review sorted_in_situ/ (add/remove as needed), then run:
    python import_images.py
"""

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

PROJECT_DIR     = Path(__file__).resolve().parent
SCRAPER_DIR     = PROJECT_DIR / "meteorite_scraper"
sys.path.insert(0, str(SCRAPER_DIR))

CLASSIFIER_PTR     = PROJECT_DIR / "training" / "best_classifier.txt"
DEFAULT_CLASSIFIER = (PROJECT_DIR / "training" / "runs" / "meteorite_classifier"
                      / "weights" / "best.pt")

DEFAULT_SOURCE  = PROJECT_DIR / "unsorted_media"
IN_SITU_DIR     = PROJECT_DIR / "sorted_in_situ"
NOT_IN_SITU_DIR = PROJECT_DIR / "sorted_not_in_situ"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif"}

# Subdirectory names inside source to skip (classifier training data lives
# in classifier_training_data/ now, but the background photos folder inside
# unsorted_media/ is still "other"-class training data, not images to sort)
TRAINING_SKIP_DIRS = {
    "53 meteorite with background photos",
}


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

def resolve_classifier(explicit_path):
    if explicit_path:
        return Path(explicit_path)
    if CLASSIFIER_PTR.exists():
        p = Path(CLASSIFIER_PTR.read_text().strip())
        if p.exists():
            return p
        print(f"WARNING: best_classifier.txt points to {p} which doesn't exist.")
    if DEFAULT_CLASSIFIER.exists():
        return DEFAULT_CLASSIFIER
    print("ERROR: No classifier model found. Run: python train_classifier.py")
    sys.exit(1)


def load_classifier(model_path):
    try:
        from ultralytics import YOLO
    except ImportError:
        print("ERROR: ultralytics not installed. Run: pip install ultralytics")
        sys.exit(1)
    model_path = Path(model_path)
    if not model_path.exists():
        print(f"ERROR: Model not found: {model_path}")
        sys.exit(1)
    print(f"Loading classifier: {model_path}")
    return YOLO(str(model_path))


def classify(model, image_path):
    """Returns (predicted_class, confidence)."""
    results  = model(str(image_path), verbose=False)
    r        = results[0]
    top_idx  = int(r.probs.top1)
    top_conf = float(r.probs.top1conf)
    return r.names[top_idx], top_conf


# ---------------------------------------------------------------------------
# Image collection
# ---------------------------------------------------------------------------

def collect_images(source_dir):
    """Walk source_dir, skipping training subdirs, hidden files, and non-images."""
    source_dir  = Path(source_dir)
    images      = []
    skipped_dirs = set()

    for p in sorted(source_dir.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in IMAGE_EXTS:
            continue
        if p.name.startswith("."):   # macOS ._resource forks, hidden files
            continue
        rel_parts = [part.lower() for part in p.relative_to(source_dir).parts[:-1]]
        skip = False
        for part in rel_parts:
            if part in TRAINING_SKIP_DIRS:
                skipped_dirs.add(part)
                skip = True
                break
        if not skip:
            images.append(p)

    if skipped_dirs:
        print(f"  Skipping classifier training dirs: {skipped_dirs}")
    return images


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def sha256_of_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_existing_hashes(directory):
    """SHA-256 of every image already in a directory (for dedup)."""
    directory = Path(directory)
    if not directory.exists():
        return set()
    hashes = set()
    for p in directory.rglob("*"):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS and not p.name.startswith("."):
            try:
                hashes.add(sha256_of_file(p))
            except Exception:
                pass
    return hashes


# ---------------------------------------------------------------------------
# Copy helper
# ---------------------------------------------------------------------------

def move_to(image_path, dest_dir, existing_hashes, dry_run):
    """
    Move image_path into dest_dir with deduplication.
    Returns 'moved', 'duplicate', or 'error'.
    """
    try:
        file_hash = sha256_of_file(image_path)
    except Exception as e:
        return "error"

    if file_hash in existing_hashes:
        return "duplicate"

    if not dry_run:
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / image_path.name
        if dest.exists():
            dest = dest_dir / f"{image_path.stem}_{file_hash[:8]}{image_path.suffix}"
        try:
            # Try an atomic rename first (fast, same-drive moves on Windows)
            image_path.rename(dest)
        except OSError:
            # Cross-drive or permission issue — fall back to copy+delete
            shutil.copy2(str(image_path), dest)
            image_path.unlink()
        existing_hashes.add(file_hash)

    return "moved"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Sort meteorite images into in_situ / other directories.")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE),
                        help=f"Directory to classify (default: unsorted_media/).")
    parser.add_argument("--model", metavar="PATH",
                        help="Classifier model path (default: training/best_classifier.txt).")
    parser.add_argument("--conf", type=float, default=0.6,
                        help="Min confidence to act; images below this are skipped (default: 0.6).")
    parser.add_argument("--in-situ-dir", default=str(IN_SITU_DIR),
                        help=f"Destination for in-situ images (default: sorted_in_situ/).")
    parser.add_argument("--not-in-situ-dir", default=str(NOT_IN_SITU_DIR),
                        help=f"Destination for other images (default: sorted_not_in_situ/).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without copying anything.")
    args = parser.parse_args()

    model = load_classifier(resolve_classifier(args.model))

    print(f"Pre-loading existing sorted hashes...")
    in_situ_hashes     = build_existing_hashes(args.in_situ_dir)
    not_in_situ_hashes = build_existing_hashes(args.not_in_situ_dir)
    print(f"  sorted_in_situ/:     {len(in_situ_hashes)} files")
    print(f"  sorted_not_in_situ/: {len(not_in_situ_hashes)} files")

    print(f"\nScanning {args.source}...")
    images = collect_images(args.source)
    print(f"  {len(images)} images to classify")

    if not images:
        print("Nothing to do.")
        return

    if args.dry_run:
        print("  [DRY RUN] — no files will be copied\n")

    in_situ_copied = in_situ_dup = other_copied = other_dup = low_conf = errors = 0

    for i, img_path in enumerate(images, 1):
        print(f"  [{i}/{len(images)}] {img_path.name}", end="")

        try:
            cls, conf = classify(model, img_path)
        except Exception as e:
            print(f"  ERROR: {e}")
            errors += 1
            continue

        print(f"  → {cls} ({conf:.0%})", end="")

        if conf < args.conf:
            print("  [low confidence, skipped]")
            low_conf += 1
            continue

        if cls == "in_situ":
            outcome = move_to(img_path, args.in_situ_dir, in_situ_hashes, args.dry_run)
            if outcome == "moved":       in_situ_copied += 1
            elif outcome == "duplicate": in_situ_dup += 1
            else: errors += 1
        else:
            outcome = move_to(img_path, args.not_in_situ_dir, not_in_situ_hashes, args.dry_run)
            if outcome == "moved":       other_copied += 1
            elif outcome == "duplicate": other_dup += 1
            else: errors += 1

        print(f"  [{outcome}]")

    print(f"""
=== Sort complete {"(DRY RUN)" if args.dry_run else ""} ===

  In-situ  → sorted_in_situ/:
    Moved       : {in_situ_copied}
    Duplicates  : {in_situ_dup}

  Other    → sorted_not_in_situ/:
    Moved       : {other_copied}
    Duplicates  : {other_dup}

  Low confidence (skipped, review manually) : {low_conf}
  Errors                                    : {errors}
  Total processed                           : {len(images)}
""")

    if not args.dry_run and in_situ_copied:
        print(f"  Review sorted_in_situ/ ({in_situ_copied} new images), then run:")
        print("    python import_images.py")


if __name__ == "__main__":
    main()
