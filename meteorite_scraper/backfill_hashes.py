#!/usr/bin/env python3
"""
backfill_hashes.py — compute and store SHA-256 file hashes for all existing
meteorite records that don't yet have one.

Run once after applying migrations/add_file_hash.sql:

    cd meteorite_scraper
    python backfill_hashes.py

Flags:
    --dry-run   Print what would be updated without writing to the database.
"""

import argparse
import hashlib
import sys
from pathlib import Path

# Allow imports from the same directory
sys.path.insert(0, str(Path(__file__).parent))

from config import DB_CONFIG, IMAGES_DIR
from database import DatabaseManager


def compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Backfill file_hash for existing meteorite records.")
    parser.add_argument('--dry-run', action='store_true', help="Show what would be updated without writing.")
    args = parser.parse_args()

    db = DatabaseManager()

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT image_id, stored_filename FROM meteorites WHERE file_hash IS NULL ORDER BY image_id"
        )
        rows = cursor.fetchall()

    total = len(rows)
    if total == 0:
        print("All records already have a file_hash. Nothing to do.")
        return

    print(f"Found {total} record(s) without a file_hash.")
    if args.dry_run:
        print("DRY RUN — no changes will be written.\n")

    updated = 0
    skipped = 0
    conflicts = 0

    for image_id, stored_filename in rows:
        if not stored_filename:
            print(f"  [{image_id}] SKIP — no stored_filename")
            skipped += 1
            continue

        filepath = IMAGES_DIR / stored_filename
        if not filepath.exists():
            print(f"  [{image_id}] SKIP — file not found: {filepath}")
            skipped += 1
            continue

        file_hash = compute_sha256(filepath)

        # Check for hash collision with an already-updated record
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT image_id FROM meteorites WHERE file_hash = %s AND image_id != %s LIMIT 1",
                (file_hash, image_id)
            )
            conflict_row = cursor.fetchone()

        if conflict_row:
            print(f"  [{image_id}] CONFLICT — same hash as ID {conflict_row[0]} ({stored_filename})")
            conflicts += 1
            continue

        if args.dry_run:
            print(f"  [{image_id}] would set file_hash={file_hash[:16]}... ({stored_filename})")
        else:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE meteorites SET file_hash = %s WHERE image_id = %s",
                    (file_hash, image_id)
                )
            print(f"  [{image_id}] updated ({stored_filename})")

        updated += 1

    print(f"\nDone. updated={updated}  skipped={skipped}  conflicts={conflicts}")
    if conflicts:
        print("Review CONFLICT rows above — they are duplicate images already in the database.")


if __name__ == '__main__':
    main()
