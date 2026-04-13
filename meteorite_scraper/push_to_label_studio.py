#!/usr/bin/env python3
"""
push_to_label_studio.py — push any meteorite DB records that are not yet
present in Label Studio.

Reads LABEL_STUDIO_URL, LABEL_STUDIO_API_KEY, and LABEL_STUDIO_PROJECT_ID
from the .env file (or environment).

Usage:
    cd meteorite_scraper
    python push_to_label_studio.py            # push missing records
    python push_to_label_studio.py --dry-run  # show what would be pushed
    python push_to_label_studio.py --all      # push every record (skip LS check)
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from config import LABEL_STUDIO_URL, LABEL_STUDIO_API_KEY, LABEL_STUDIO_PROJECT_ID
from database import DatabaseManager
from label_studio_client import push_task, _session


def fetch_existing_image_ids() -> set:
    """Return the set of image_ids already present as tasks in Label Studio."""
    if not LABEL_STUDIO_API_KEY or not LABEL_STUDIO_PROJECT_ID:
        raise RuntimeError("LABEL_STUDIO_API_KEY or LABEL_STUDIO_PROJECT_ID not set in .env")

    session = _session()
    base = LABEL_STUDIO_URL.rstrip('/')

    # Paginate through tasks using only the fields we need.
    url = f"{base}/api/tasks"
    existing = set()
    page = 1
    while True:
        r = session.get(url, params={
            "project": LABEL_STUDIO_PROJECT_ID,
            "page": page,
            "page_size": 100,
            "fields": "data",
        }, timeout=30)
        r.raise_for_status()
        body = r.json()
        tasks = body if isinstance(body, list) else body.get("tasks", [])
        if not tasks:
            break
        for task in tasks:
            image_id = task.get("data", {}).get("image_id")
            if image_id is not None:
                existing.add(int(image_id))
        if len(tasks) < 100:
            break
        page += 1

    return existing


def main():
    parser = argparse.ArgumentParser(description="Bulk-push missing DB records to Label Studio.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be pushed without sending.")
    parser.add_argument("--all", action="store_true", help="Push every DB record, skipping the Label Studio check.")
    args = parser.parse_args()

    if not LABEL_STUDIO_API_KEY or not LABEL_STUDIO_PROJECT_ID:
        print("ERROR: LABEL_STUDIO_API_KEY and LABEL_STUDIO_PROJECT_ID must be set in .env")
        sys.exit(1)

    db = DatabaseManager()

    # Fetch all DB records (unpaginated for the push script)
    with db.get_connection() as conn:
        from psycopg2.extras import RealDictCursor
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM meteorites ORDER BY image_id")
        all_records = cursor.fetchall()

    total_db = len(all_records)
    print(f"Database contains {total_db} record(s).")

    if args.all:
        to_push = list(all_records)
        print("--all flag set, pushing every record.")
    else:
        print("Fetching existing Label Studio tasks...", end=" ", flush=True)
        existing_ids = fetch_existing_image_ids()
        print(f"found {len(existing_ids)} task(s).")
        to_push = [r for r in all_records if r["image_id"] not in existing_ids]

    if not to_push:
        print("Nothing to push — Label Studio is already up to date.")
        return

    print(f"{len(to_push)} record(s) to push.")
    if args.dry_run:
        print("DRY RUN — no data will be sent.\n")

    pushed = 0
    failed = 0
    for record in to_push:
        image_id = record["image_id"]
        name = record.get("meteorite_name") or "unnamed"
        filename = record.get("stored_filename", "")

        if args.dry_run:
            print(f"  [{image_id}] would push: {filename} ({name})")
            pushed += 1
        else:
            ok = push_task(dict(record))
            if ok:
                print(f"  [{image_id}] pushed: {filename} ({name})")
                pushed += 1
            else:
                print(f"  [{image_id}] FAILED: {filename} ({name})")
                failed += 1

    print(f"\nDone. pushed={pushed}  failed={failed}")


if __name__ == "__main__":
    main()
