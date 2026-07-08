#!/usr/bin/env python3
"""
One-off import of Winthrop mock meteorite photos.

Copies images from the source directory into the DB with:
  meteorite_name  = Winthrop_Mock_<n>
  in_situ         = True
  mock_meteorite  = True
  photo_quality   = High
  needs_review    = False
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from config import IMAGES_DIR, METADATA_DIR
from database import DatabaseManager

SRC_DIR = Path(r"C:\Users\charl\OneDrive\Documents\_Projects\Meteorites\Mock_Meteorite_Photos")
EXTS = {'.jpg', '.jpeg', '.png', '.webp'}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    dry_run = '--dry-run' in sys.argv

    if not SRC_DIR.is_dir():
        print(f"ERROR: directory not found: {SRC_DIR}")
        sys.exit(1)

    db = DatabaseManager()
    images = sorted(f for f in SRC_DIR.iterdir() if f.is_file() and f.suffix.lower() in EXTS)
    print(f"Found {len(images)} images in {SRC_DIR}")
    print(f"Dry run: {dry_run}\n")

    imported = skipped_dup = skipped_err = 0

    for n, src in enumerate(images, start=1):
        name = f"Winthrop_Mock_{n}"
        try:
            file_hash = sha256(src)
            dup_id = db.hash_exists(file_hash)
            if dup_id:
                print(f"  SKIP (dup of ID {dup_id}): {src.name}")
                skipped_dup += 1
                continue

            with Image.open(src) as img:
                width, height = img.size

            file_size = src.stat().st_size

            if dry_run:
                print(f"  WOULD IMPORT: {src.name} -> {name}  ({width}x{height})")
                imported += 1
                continue

            db_data = {
                'meteorite_name':          name,
                'original_filename':       src.name,
                'stored_filename':         src.name[:80],  # temporary
                'source_url':              src.as_uri(),
                'page_url':                None,
                'photo_page_url':          None,
                'file_format':             'jpg',
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
                'needs_review':            False,
                'notes':                   None,
                'file_hash':               file_hash,
            }

            image_id = db.insert_meteorite(db_data)
            stored_name = f"{image_id:06d}_{name}.jpg"
            dest = IMAGES_DIR / stored_name

            shutil.copy2(str(src), str(dest))

            db.update_meteorite(image_id, {
                'stored_filename':  stored_name,
                'in_situ':          True,
                'mock_meteorite':   True,
                'from_drone':       False,
                'sectioned':        False,
                'negative_sample':  False,
                'photo_quality':    'High',
            })

            meta = {'source_path': str(src), 'original_filename': src.name, 'meteorite_name': name}
            json_path = METADATA_DIR / (Path(stored_name).stem + '.json')
            json_path.write_text(json.dumps(meta, indent=2))

            print(f"  IMPORTED ID {image_id}: {src.name} -> {stored_name}")
            imported += 1

        except Exception as e:
            print(f"  ERROR: {src.name}: {e}")
            skipped_err += 1

    print(f"\nDone: {imported} imported, {skipped_dup} skipped (duplicate), {skipped_err} errors")


if __name__ == '__main__':
    main()
