#!/usr/bin/env python3
"""
import_images.py â€” Import a directory of images into the annotation pipeline:
  1. Validate each image
  2. SHA-256 dedup against the database (skips exact duplicates)
  3. Copy to meteorite_scraper/images/
  4. Insert a database record with image_context='in_situ'
  5. Push to Label Studio as a new task

The default source is sorted_in_situ/, but you can point it at any directory â€”
including unsorted_media/meteorites_in_situ/ for manual additions.

Usage:
    python import_images.py                            # import sorted_in_situ/
    python import_images.py --source path/to/dir       # import a specific directory
    python import_images.py --dry-run                  # preview without writing
    python import_images.py --skip-ls                  # skip Label Studio push

After import, run:
    python auto_annotate.py    to push detector predictions to the new tasks
"""

import argparse
import hashlib
import sys
from pathlib import Path

PROJECT_DIR  = Path(__file__).resolve().parent.parent
SCRAPER_DIR = PROJECT_DIR / "meteorite_scraper"
sys.path.insert(0, str(SCRAPER_DIR))

from dotenv import load_dotenv
load_dotenv(SCRAPER_DIR / ".env")

from config   import IMAGES_DIR
from database import DatabaseManager
from utils    import generate_filename, validate_image

DEFAULT_SOURCE = PROJECT_DIR / "sorted_in_situ"
IMAGE_EXTS     = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif"}


def collect_images(source_dir):
    source_dir = Path(source_dir)
    if not source_dir.exists():
        print(f"ERROR: Directory not found: {source_dir}")
        sys.exit(1)
    return sorted(
        p for p in source_dir.rglob("*")
        if p.is_file()
        and p.suffix.lower() in IMAGE_EXTS
        and not p.name.startswith(".")
    )


def import_image(image_path, db, push_ls, dry_run):
    """
    Import a single image into the pipeline.
    Returns one of: 'imported', 'duplicate', 'invalid', 'error'.
    """
    image_path = Path(image_path)
    try:
        image_data = image_path.read_bytes()
    except Exception as e:
        print(f"    ERROR reading: {e}")
        return "error"

    image_info = validate_image(image_data)
    if not image_info:
        return "invalid"

    file_hash = hashlib.sha256(image_data).hexdigest()
    dup_id    = db.hash_exists(file_hash)
    if dup_id:
        return "duplicate"

    ext = image_info["format"]
    if ext == "jpeg":
        ext = "jpg"

    filename = generate_filename(image_path.as_uri(), None, ext)
    dest     = Path(IMAGES_DIR) / filename

    if not dry_run:
        dest.write_bytes(image_data)

        db_record = {
            "meteorite_name":          None,
            "original_filename":       image_path.name,
            "stored_filename":         filename,
            "source_url":              str(image_path),
            "page_url":                None,
            "photo_page_url":          None,
            "file_format":             ext,
            "file_size_bytes":         len(image_data),
            "width_px":                image_info.get("width"),
            "height_px":               image_info.get("height"),
            "primary_type":            None,
            "secondary_type":          None,
            "detailed_classification": None,
            "mass_grams":              None,
            "fall_or_find":            None,
            "discovery_date":          None,
            "discovery_location":      None,
            "discovery_latitude":      None,
            "discovery_longitude":     None,
            "terrain_type":            None,
            "image_context":           "in_situ",
            "viewing_angle":           None,
            "background_type":         None,
            "lighting_type":           None,
            "license":                 None,
            "photographer":            None,
            "needs_review":            True,
            "notes":                   None,
            "file_hash":               file_hash,
        }
        image_id = db.insert_meteorite(db_record)

        if push_ls and image_id:
            try:
                from label_studio_client import push_task
                push_task({**db_record, "image_id": image_id})
            except Exception as e:
                print(f"    WARNING: Label Studio push failed: {e}")

    return "imported"


def main():
    parser = argparse.ArgumentParser(
        description="Import images from a directory into the annotation pipeline.")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE),
                        help="Directory to import (default: sorted_in_situ/).")
    parser.add_argument("--skip-ls", action="store_true",
                        help="Don't push to Label Studio.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without writing anything.")
    args = parser.parse_args()

    db     = DatabaseManager()
    images = collect_images(args.source)

    print(f"Importing from: {args.source}")
    print(f"Found {len(images)} image(s)")
    if args.dry_run:
        print("[DRY RUN] â€” nothing will be written\n")
    if not images:
        print("Nothing to do.")
        return

    imported = duplicate = invalid = errors = 0

    for i, img_path in enumerate(images, 1):
        print(f"  [{i}/{len(images)}] {img_path.name}", end="  ")
        outcome = import_image(img_path, db, not args.skip_ls, args.dry_run)
        print(f"[{outcome}]")
        if outcome == "imported":   imported  += 1
        elif outcome == "duplicate": duplicate += 1
        elif outcome == "invalid":   invalid   += 1
        else:                        errors    += 1

    print(f"""
=== Import complete {"(DRY RUN)" if args.dry_run else ""} ===
  Imported   : {imported}
  Duplicates : {duplicate}
  Invalid    : {invalid}
  Errors     : {errors}
  Total      : {len(images)}
""")

    if imported and not args.dry_run:
        print(f"  {imported} new image(s) in Label Studio.")
        print("  Run: python auto_annotate.py  to push detector predictions.")


if __name__ == "__main__":
    main()
