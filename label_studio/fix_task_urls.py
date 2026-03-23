#!/usr/bin/env python3
"""
Fix existing Label Studio task image URLs to include the 'images/' subdirectory prefix.

Before: /data/local-files/?d=filename.jpg
After:  /data/local-files/?d=images/filename.jpg

Usage:
    python label_studio/fix_task_urls.py --username EMAIL --password PASS --project-id 2
    python label_studio/fix_task_urls.py --api-key YOUR_API_KEY --project-id 2
"""
import argparse
import os
import sys
import requests

LABEL_STUDIO_URL = os.getenv("LABEL_STUDIO_URL", "http://localhost:8080")
OLD_PREFIX = "/data/local-files/?d="
NEW_PREFIX = "/data/local-files/?d=images/"


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


def fix_tasks(project_id, session, base):
    # Fetch all tasks (paginated)
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

    print(f"Found {len(tasks)} tasks in project {project_id}.")

    updated = 0
    skipped = 0
    errors = 0

    for task in tasks:
        from urllib.parse import unquote
        image_url = task.get("data", {}).get("image", "")
        # Normalise URL-encoded backslashes (Windows storage sync artefact)
        normalised = unquote(image_url).replace("\\", "/")

        if normalised.startswith(NEW_PREFIX):
            if normalised == image_url:
                skipped += 1
                continue
            # URL was correct after normalization but had encoded backslashes — fix it
            new_url = normalised
        elif normalised.startswith(OLD_PREFIX):
            filename = normalised[len(OLD_PREFIX):]
            filename = filename.lstrip("/")
            if filename.startswith("images/"):
                filename = filename[len("images/"):]
            new_url = NEW_PREFIX + filename
        else:
            skipped += 1
            continue

        r = session.patch(
            f"{base}/api/tasks/{task['id']}",
            json={"data": {**task["data"], "image": new_url}},
        )
        if r.ok:
            updated += 1
        else:
            print(f"  ERROR task {task['id']}: {r.status_code} {r.text[:120]}")
            errors += 1

    print(f"Updated: {updated}  |  Already correct: {skipped}  |  Errors: {errors}")


def main():
    parser = argparse.ArgumentParser(description="Fix Label Studio task image URL prefixes")
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

    fix_tasks(args.project_id, session, base)


if __name__ == "__main__":
    main()
