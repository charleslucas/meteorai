#!/usr/bin/env python3
"""
Patch Label Studio tasks that are missing database metadata (image_id, meteorite_name, etc.)
by looking up each task's filename in the meteorite database.

Run this after syncing storage or importing new images.

Usage:
    python label_studio/sync_task_metadata.py --username EMAIL --password PASS --project-id 2
    python label_studio/sync_task_metadata.py --api-key LEGACY_TOKEN --project-id 2
"""
import argparse
import os
import sys
from pathlib import Path
import requests

LABEL_STUDIO_URL = os.getenv("LABEL_STUDIO_URL", "http://localhost:8080")

SCRAPER_DIR = Path(__file__).resolve().parent.parent / "meteorite_scraper"
sys.path.insert(0, str(SCRAPER_DIR))
from database import DatabaseManager
from urllib.parse import unquote


def get_session_with_credentials(base, username, password):
    session = requests.Session()
    r = session.get(f"{base}/user/login")
    r.raise_for_status()
    csrf = session.cookies.get("csrftoken", "")
    session.post(f"{base}/user/login", data={
        "email": username,
        "password": password,
        "csrfmiddlewaretoken": csrf,
    }, headers={"Referer": f"{base}/user/login"})
    csrf = session.cookies.get("csrftoken", csrf)
    session.headers.update({
        "Content-Type": "application/json",
        "X-CSRFToken": csrf,
    })
    return session


def fetch_all_tasks(session, base, project_id):
    tasks = []
    page = 1
    while True:
        r = session.get(
            f"{base}/api/tasks",
            params={"project": project_id, "page": page, "page_size": 100},
        )
        r.raise_for_status()
        data = r.json()
        batch = data.get("tasks", data) if isinstance(data, dict) else data
        if not batch:
            break
        tasks.extend(batch)
        if isinstance(data, dict) and not data.get("next"):
            break
        page += 1
    return tasks


def filename_from_url(image_url):
    """Extract stored_filename from a Label Studio local-files URL."""
    # /data/local-files/?d=images/filename.jpg   -> filename.jpg
    # /data/local-files/?d=images%5Cfilename.jpg -> filename.jpg  (Windows backslash)
    # /data/local-files/?d=filename.jpg          -> filename.jpg
    if "?d=" not in image_url:
        return None
    path = unquote(image_url.split("?d=", 1)[1])
    # Normalise both slash types
    return Path(path.replace("\\", "/")).name


def build_db_lookup(db):
    """Return a dict of stored_filename -> db record."""
    records = db.get_all_meteorites(limit=100000)
    return {r["stored_filename"]: r for r in records if r.get("stored_filename")}


def main():
    parser = argparse.ArgumentParser(description="Patch missing metadata on Label Studio tasks")
    parser.add_argument("--api-key", default=os.getenv("LABEL_STUDIO_API_KEY"))
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--project-id", type=int, required=True)
    args = parser.parse_args()

    base = LABEL_STUDIO_URL.rstrip("/")

    if args.username and args.password:
        session = get_session_with_credentials(base, args.username, args.password)
        print(f"Logged in as {args.username}.")
    elif args.api_key:
        session = requests.Session()
        prefix = "Bearer" if args.api_key.startswith("eyJ") else "Token"
        session.headers.update({
            "Authorization": f"{prefix} {args.api_key}",
            "Content-Type": "application/json",
        })
    else:
        print("ERROR: Provide --username/--password or --api-key.")
        sys.exit(1)

    print("Loading tasks from Label Studio...")
    tasks = fetch_all_tasks(session, base, args.project_id)
    print(f"Found {len(tasks)} tasks.")

    print("Loading meteorite records from database...")
    db = DatabaseManager()
    db_lookup = build_db_lookup(db)
    print(f"Loaded {len(db_lookup)} database records.")

    updated = 0
    skipped = 0
    not_found = 0
    errors = 0

    for task in tasks:
        data = task.get("data", {})

        # Skip if already has metadata
        if data.get("image_id"):
            skipped += 1
            continue

        filename = filename_from_url(data.get("image", ""))
        if not filename:
            skipped += 1
            continue

        rec = db_lookup.get(filename)
        if not rec:
            print(f"  No DB record for: {filename}")
            not_found += 1
            continue

        new_data = {
            **data,
            "image_id":               rec["image_id"],
            "meteorite_name":         rec.get("meteorite_name") or "Unknown",
            "primary_type":           rec.get("primary_type") or "",
            "detailed_classification": rec.get("detailed_classification") or "",
            "image_context":          rec.get("image_context") or "",
            "mass_grams":             str(rec["mass_grams"]) if rec.get("mass_grams") else "",
        }

        r = session.patch(
            f"{base}/api/tasks/{task['id']}",
            json={"data": new_data},
        )
        if r.ok:
            updated += 1
        else:
            print(f"  ERROR task {task['id']}: {r.status_code} {r.text[:120]}")
            errors += 1

    print(f"\nUpdated: {updated}  |  Already had metadata: {skipped}  |  Not in DB: {not_found}  |  Errors: {errors}")


if __name__ == "__main__":
    main()
