#!/usr/bin/env python3
"""
sort_media.py — Classify images in a directory as in-situ (useful) or other,
then route them accordingly:

  in_situ  → deduplicate against the DB → copy to images/, insert DB record,
              push to Label Studio as a new task ready for annotation
  other    → deduplicate against existing sorted files → copy to sorted_not_in_situ/

Usage:
    python sort_media.py                          # sort all of unsorted_media/
    python sort_media.py --source path/to/dir     # sort a specific directory
    python sort_media.py --dry-run                # preview without moving anything
    python sort_media.py --conf 0.7               # only act on high-confidence results
    python sort_media.py --skip-ls                # don't push to Label Studio

Subdirectories named 'meteorites_on_ground' and '53 Meteorite with background
photos' inside the source are skipped (they are classifier training data, not
images to be sorted).
"""

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

PROJECT_DIR  = Path(__file__).resolve().parent
SCRAPER_DIR  = PROJECT_DIR / "meteorite_scraper"
sys.path.insert(0, str(SCRAPER_DIR))

from dotenv import load_dotenv
load_dotenv(SCRAPER_DIR / ".env")

from config       import IMAGES_DIR
from database     import DatabaseManager
from utils        import generate_filename, validate_image

CLASSIFIER_PTR  = PROJECT_DIR / "training" / "best_classifier.txt"
DEFAULT_CLASSIFIER = (PROJECT_DIR / "training" / "runs" / "meteorite_classifier"
                      / "weights" / "best.pt")

DEFAULT_SOURCE  = PROJECT_DIR / "unsorted_media"
NOT_IN_SITU_DIR = PROJECT_DIR / "sorted_not_in_situ"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif"}

# Subdirectory names inside source that are training data — skip them
TRAINING_SKIP_DIRS = {
    "meteorites_on_ground",
    "53 meteorite with background photos",   # lowercased for comparison
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
    """
    Returns (predicted_class, confidence).
    predicted_class is the string name ('in_situ' or 'other').
    """
    results = model(str(image_path), verbose=False)
    r = results[0]
    top_idx  = int(r.probs.top1)
    top_conf = float(r.probs.top1conf)
    cls_name = r.names[top_idx]
    return cls_name, top_conf


# ---------------------------------------------------------------------------
# Image collection
# ---------------------------------------------------------------------------

def collect_images(source_dir):
    """Walk source_dir, skipping training subdirectories and non-image files."""
    source_dir = Path(source_dir)
    images = []
    skipped_dirs = set()

    for p in sorted(source_dir.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in IMAGE_EXTS:
            continue
        if p.name.startswith("."):      # skip macOS ._resource forks and hidden files
            continue
        # Check if any parent directory is a training skip dir
        rel_parts = [part.lower() for part in p.relative_to(source_dir).parts]
        skip = False
        for part in rel_parts[:-1]:   # all but the filename itself
            if part in TRAINING_SKIP_DIRS:
                skipped_dirs.add(part)
                skip = True
                break
        if not skip:
            images.append(p)

    if skipped_dirs:
        print(f"  Skipped training dirs: {skipped_dirs}")
    return images


# ---------------------------------------------------------------------------
# Deduplication helpers
# ---------------------------------------------------------------------------

def sha256_of_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_not_in_situ_hashes(directory):
    """Compute SHA-256 of every file already in sorted_not_in_situ/."""
    directory = Path(directory)
    if not directory.exists():
        return set()
    hashes = set()
    for p in directory.iterdir():
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            try:
                hashes.add(sha256_of_file(p))
            except Exception:
                pass
    return hashes


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def import_as_in_situ(image_path, db, push_ls, dry_run):
    """
    Copy image into the annotation pipeline:
      - validate image
      - SHA-256 dedup against DB
      - copy to IMAGES_DIR
      - insert DB record with image_context='in_situ'
      - push to Label Studio

    Returns 'imported', 'duplicate', or 'invalid'.
    """
    image_path = Path(image_path)
    try:
        image_data = image_path.read_bytes()
    except Exception as e:
        print(f"    ERROR reading file: {e}")
        return "error"

    image_info = validate_image(image_data)
    if not image_info:
        return "invalid"

    file_hash = hashlib.sha256(image_data).hexdigest()
    dup_id = db.hash_exists(file_hash)
    if dup_id:
        return "duplicate"

    ext = image_info["format"]
    if ext == "jpeg":
        ext = "jpg"

    canonical_url = image_path.as_uri()
    filename      = generate_filename(canonical_url, None, ext)
    dest          = Path(IMAGES_DIR) / filename

    if not dry_run:
        dest.write_bytes(image_data)

        db_record = {
            "original_filename": image_path.name,
            "stored_filename":   filename,
            "source_url":        str(image_path),
            "file_format":       ext,
            "file_size_bytes":   len(image_data),
            "width_px":          image_info.get("width"),
            "height_px":         image_info.get("height"),
            "image_context":     "in_situ",
            "needs_review":      True,
            "file_hash":         file_hash,
        }
        image_id = db.insert_meteorite(db_record)

        if push_ls and image_id:
            try:
                from label_studio_client import push_task
                push_task({**db_record, "image_id": image_id})
            except Exception as e:
                print(f"    WARNING: Label Studio push failed: {e}")

    return "imported"


def copy_to_not_in_situ(image_path, not_in_situ_dir, existing_hashes, dry_run):
    """
    Deduplicate and copy to sorted_not_in_situ/.
    Returns 'copied' or 'duplicate'.
    """
    image_path    = Path(image_path)
    not_in_situ_dir = Path(not_in_situ_dir)

    file_hash = sha256_of_file(image_path)
    if file_hash in existing_hashes:
        return "duplicate"

    if not dry_run:
        not_in_situ_dir.mkdir(parents=True, exist_ok=True)
        dest = not_in_situ_dir / image_path.name
        # Avoid filename collision (different files, same name)
        if dest.exists():
            dest = not_in_situ_dir / f"{image_path.stem}_{file_hash[:8]}{image_path.suffix}"
        shutil.copy2(image_path, dest)
        existing_hashes.add(file_hash)

    return "copied"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Classify and route meteorite images.")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE),
                        help=f"Directory to sort (default: {DEFAULT_SOURCE}).")
    parser.add_argument("--model", metavar="PATH",
                        help="Path to classifier .pt file (default: training/best_classifier.txt).")
    parser.add_argument("--conf", type=float, default=0.6,
                        help="Minimum confidence to act on a prediction (default: 0.6). "
                             "Images below this threshold are skipped.")
    parser.add_argument("--not-in-situ-dir", default=str(NOT_IN_SITU_DIR),
                        help=f"Destination for non-in-situ images (default: {NOT_IN_SITU_DIR}).")
    parser.add_argument("--skip-ls", action="store_true",
                        help="Don't push in-situ imports to Label Studio.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Classify and report without copying or writing anything.")
    args = parser.parse_args()

    # Load model and DB
    model_path = resolve_classifier(args.model)
    model      = load_classifier(model_path)
    db         = DatabaseManager()

    # Pre-compute hashes of already-sorted files to dedup on the fly
    print(f"Loading existing not-in-situ hashes from {args.not_in_situ_dir}...")
    not_in_situ_hashes = build_not_in_situ_hashes(args.not_in_situ_dir)
    print(f"  {len(not_in_situ_hashes)} files already in sorted_not_in_situ/")

    # Collect images to process
    print(f"\nScanning {args.source}...")
    images = collect_images(args.source)
    print(f"  {len(images)} images to classify")

    if not images:
        print("Nothing to do.")
        return

    if args.dry_run:
        print("  [DRY RUN] — no files will be copied or written\n")

    # Counters
    counts = {
        "in_situ_imported":   0,
        "in_situ_duplicate":  0,
        "in_situ_invalid":    0,
        "other_copied":       0,
        "other_duplicate":    0,
        "low_confidence":     0,
        "errors":             0,
    }

    for i, img_path in enumerate(images, 1):
        print(f"  [{i}/{len(images)}] {img_path.name}", end="")

        try:
            cls, conf = classify(model, img_path)
        except Exception as e:
            print(f"  ERROR classifying: {e}")
            counts["errors"] += 1
            continue

        print(f"  → {cls} ({conf:.0%})", end="")

        if conf < args.conf:
            print("  [low confidence, skipped]")
            counts["low_confidence"] += 1
            continue

        if cls == "in_situ":
            outcome = import_as_in_situ(img_path, db, not args.skip_ls, args.dry_run)
            counts[f"in_situ_{outcome}"] = counts.get(f"in_situ_{outcome}", 0) + 1
            print(f"  [{outcome}]")
        else:
            outcome = copy_to_not_in_situ(
                img_path, args.not_in_situ_dir, not_in_situ_hashes, args.dry_run
            )
            counts[f"other_{outcome}"] = counts.get(f"other_{outcome}", 0) + 1
            print(f"  [{outcome}]")

    # Summary
    print(f"""
=== Sort complete {"(DRY RUN)" if args.dry_run else ""} ===

  In-situ:
    Imported to annotation pipeline : {counts['in_situ_imported']}
    Duplicates (already in DB)      : {counts['in_situ_duplicate']}
    Invalid image files             : {counts.get('in_situ_invalid', 0)}

  Other (not in-situ):
    Copied to sorted_not_in_situ/   : {counts['other_copied']}
    Duplicates (already sorted)     : {counts['other_duplicate']}

  Low confidence (skipped)          : {counts['low_confidence']}
  Errors                            : {counts['errors']}
  Total processed                   : {len(images)}
""")

    if counts["in_situ_imported"] and not args.dry_run:
        print(f"  {counts['in_situ_imported']} new in-situ images added to Label Studio.")
        print("  Run: python auto_annotate.py  to push predictions to the new tasks.")


if __name__ == "__main__":
    main()
