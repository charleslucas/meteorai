#!/usr/bin/env python3
"""
bulk_import.py - Import a directory of images into the meteorite database.

Skips images already in the DB (checked by SHA-256 hash).
Sets in_situ=False, needs_review=True for all imported images.

Usage:
    python bulk_import.py <directory>
    python bulk_import.py <directory> --dry-run
    python bulk_import.py <directory> --in-situ      # mark as in-situ
"""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from config import IMAGES_DIR, METADATA_DIR
from database import DatabaseManager

EXTS = {'.jpg', '.jpeg', '.png', '.webp'}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def safe_stored_name(src: Path, image_id: int) -> str:
    stem = src.stem[:40].replace(' ', '_')
    ext = src.suffix.lower().lstrip('.')
    if ext == 'jpeg':
        ext = 'jpg'
    return f"{image_id:06d}_{stem}.{ext}"


def main():
    parser = argparse.ArgumentParser(description="Bulk import images into meteorite DB")
    parser.add_argument('directory', help="Directory of images to import")
    parser.add_argument('--dry-run', action='store_true', help="Preview without inserting")
    parser.add_argument('--in-situ', action='store_true', help="Mark images as in-situ")
    args = parser.parse_args()

    src_dir = Path(args.directory)
    if not src_dir.is_dir():
        print(f"ERROR: not a directory: {src_dir}")
        sys.exit(1)

    db = DatabaseManager()

    images = sorted(f for f in src_dir.rglob('*') if f.is_file() and f.suffix.lower() in EXTS)
    print(f"Found {len(images)} images in {src_dir}")
    print(f"Dry run: {args.dry_run}  |  In-situ: {args.in_situ}")
    print()

    imported = 0
    skipped_dup = 0
    skipped_err = 0

    for src in images:
        try:
            file_hash = sha256(src)
            dup_id = db.hash_exists(file_hash)
            if dup_id:
                print(f"  SKIP (dup of ID {dup_id}): {src.name}")
                skipped_dup += 1
                continue

            with Image.open(src) as img:
                width, height = img.size
                fmt = img.format or 'JPEG'

            file_size = src.stat().st_size
            ext = src.suffix.lower().lstrip('.')
            if ext == 'jpeg':
                ext = 'jpg'

            if args.dry_run:
                print(f"  WOULD IMPORT: {src.name}  ({width}x{height})")
                imported += 1
                continue

            # Reserve a DB row to get the image_id, then rename the file to include it
            db_data = {
                'meteorite_name':          None,
                'original_filename':       src.name,
                'stored_filename':         src.name[:80],  # temporary; updated below
                'source_url':              src.as_uri(),
                'page_url':                None,
                'photo_page_url':          None,
                'file_format':             ext,
                'file_size_bytes':         file_size,
                'width_px':                width,
                'height_px':               height,
                'primary_type':            None,
                'secondary_type':          None,
                'detailed_classification': None,
                'mass_grams':              None,
                'fall_or_find':            None,
                'discovery_date':          None,
                'discovery_location':      None,
                'discovery_latitude':      None,
                'discovery_longitude':     None,
                'terrain_type':            None,
                'image_context':           None,
                'viewing_angle':           None,
                'background_type':         None,
                'lighting_type':           None,
                'license':                 None,
                'photographer':            None,
                'needs_review':            True,
                'notes':                   None,
                'file_hash':               file_hash,
            }

            image_id = db.insert_meteorite(db_data)
            stored_name = safe_stored_name(src, image_id)
            dest = IMAGES_DIR / stored_name

            shutil.copy2(str(src), str(dest))

            # Update stored_filename to the final name
            db.update_meteorite(image_id, {'stored_filename': stored_name})

            # Set boolean flags
            db.update_meteorite(image_id, {
                'in_situ':    args.in_situ,
                'from_drone': False,
                'sectioned':  False,
                'mock_meteorite': False,
            })

            # Save minimal metadata JSON
            meta = {'source_path': str(src), 'original_filename': src.name}
            json_path = METADATA_DIR / (Path(stored_name).stem + '.json')
            json_path.write_text(json.dumps(meta, indent=2))

            print(f"  IMPORTED ID {image_id}: {src.name} -> {stored_name}")
            imported += 1

        except Exception as e:
            print(f"  ERROR: {src.name}: {e}")
            skipped_err += 1

    print()
    print(f"Done: {imported} imported, {skipped_dup} skipped (duplicate), {skipped_err} errors")


if __name__ == '__main__':
    main()
