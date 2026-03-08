#!/usr/bin/env python3
"""
Export Label Studio annotations to YOLO and COCO formats.

Usage:
    python label_studio/export_annotations.py --project-id 2 --username your@email.com --password yourpassword
    python label_studio/export_annotations.py --project-id 2 --username your@email.com --password yourpassword --format yolo
    python label_studio/export_annotations.py --project-id 2 --username your@email.com --password yourpassword --format coco
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import requests

# Add meteorite_scraper to path
SCRAPER_DIR = Path(__file__).resolve().parent.parent / "meteorite_scraper"
sys.path.insert(0, str(SCRAPER_DIR))

from config import IMAGES_DIR

LABEL_STUDIO_URL = os.getenv("LABEL_STUDIO_URL", "http://localhost:8080")

EXPORTS_DIR = Path(__file__).resolve().parent / "exports"
YOLO_DIR = EXPORTS_DIR / "yolo"
COCO_DIR = EXPORTS_DIR / "coco"

# Label-to-index mapping (must match training config)
LABEL_MAP = {
    "meteorite": 0,
    "fusion_crust": 1,
    "regmaglypts": 2,
    "metal_flake": 3,
    "scale_reference": 4,
}


def get_session(base_url, username, password):
    """Log in and return an authenticated requests session."""
    session = requests.Session()

    # Get CSRF token
    r = session.get(f"{base_url}/user/login")
    r.raise_for_status()
    csrf = session.cookies.get("csrftoken", "")

    # Log in
    r = session.post(f"{base_url}/user/login", data={
        "email": username,
        "password": password,
        "csrfmiddlewaretoken": csrf,
    }, headers={"Referer": f"{base_url}/user/login"})
    r.raise_for_status()

    # Update CSRF and set headers for API calls
    csrf = session.cookies.get("csrftoken", csrf)
    session.headers.update({
        "Content-Type": "application/json",
        "X-CSRFToken": csrf,
    })

    # Verify login
    r = session.get(f"{base_url}/api/projects")
    if r.status_code in (401, 403):
        raise Exception(f"Login failed. Check your username and password.")
    r.raise_for_status()
    print(f"Logged in successfully as {username}.")
    return session


def get_tasks(session, base_url, project_id):
    """Fetch all annotated tasks for a project."""
    tasks = []
    page = 1
    while True:
        r = session.get(
            f"{base_url}/api/tasks",
            params={"project": project_id, "page": page, "page_size": 100, "only_with_annotations": True}
        )
        r.raise_for_status()
        data = r.json()
        results = data.get("tasks", data) if isinstance(data, dict) else data
        if not results:
            break
        tasks.extend(results)
        if isinstance(data, dict) and not data.get("next"):
            break
        page += 1
    return tasks


def get_filename_from_task(task):
    """Extract the image filename from a task's data."""
    image_url = task["data"].get("image", "")
    if "?d=" in image_url:
        return image_url.split("?d=")[-1]
    return image_url.split("/")[-1]


def get_image_dimensions(task):
    """Get original image dimensions from annotation results or PIL."""
    for annotation in task.get("annotations", []):
        for result in annotation.get("result", []):
            if "original_width" in result:
                return result["original_width"], result["original_height"]

    # Fallback: read from image file
    filename = get_filename_from_task(task)
    img_path = IMAGES_DIR / filename
    if img_path.exists():
        from PIL import Image
        with Image.open(img_path) as img:
            return img.size

    return None, None


def export_yolo(tasks):
    """Convert RectangleLabels annotations to YOLO format."""
    YOLO_DIR.mkdir(parents=True, exist_ok=True)

    with open(YOLO_DIR / "classes.txt", "w") as f:
        for label in sorted(LABEL_MAP, key=LABEL_MAP.get):
            f.write(label + "\n")

    count = 0
    for task in tasks:
        if not task.get("annotations"):
            continue

        filename = get_filename_from_task(task)
        txt_name = Path(filename).stem + ".txt"
        lines = []

        for annotation in task["annotations"]:
            for result in annotation.get("result", []):
                if result["type"] != "rectanglelabels":
                    continue
                value = result["value"]
                label = value["rectanglelabels"][0]
                if label not in LABEL_MAP:
                    continue

                x = value["x"] / 100.0
                y = value["y"] / 100.0
                w = value["width"] / 100.0
                h = value["height"] / 100.0
                cx = x + w / 2
                cy = y + h / 2
                lines.append(f"{LABEL_MAP[label]} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")

        if lines:
            with open(YOLO_DIR / txt_name, "w") as f:
                f.write("\n".join(lines) + "\n")
            count += 1

    print(f"Exported {count} YOLO annotation files to {YOLO_DIR}")
    print(f"Classes file: {YOLO_DIR / 'classes.txt'}")


def export_coco(tasks):
    """Convert PolygonLabels annotations to COCO format."""
    COCO_DIR.mkdir(parents=True, exist_ok=True)

    coco = {
        "info": {
            "description": "MeteorAI Meteorite Segmentation Dataset",
            "date_created": datetime.now().isoformat(),
        },
        "images": [],
        "annotations": [],
        "categories": [
            {"id": idx, "name": name}
            for name, idx in sorted(LABEL_MAP.items(), key=lambda x: x[1])
        ],
    }

    ann_id = 1
    images_added = 0

    for task in tasks:
        if not task.get("annotations"):
            continue

        image_id = task["data"].get("image_id")
        filename = get_filename_from_task(task)
        orig_w, orig_h = get_image_dimensions(task)

        if not orig_w:
            print(f"  Warning: Could not determine dimensions for {filename}, skipping.")
            continue

        coco_image_id = task["id"]
        coco["images"].append({
            "id": coco_image_id,
            "file_name": filename,
            "width": orig_w,
            "height": orig_h,
            "meteorite_image_id": image_id,
        })
        images_added += 1

        for annotation in task["annotations"]:
            for result in annotation.get("result", []):
                if result["type"] != "polygonlabels":
                    continue
                value = result["value"]
                label = value["polygonlabels"][0]
                if label not in LABEL_MAP:
                    continue

                points = value["points"]
                abs_points = []
                for px, py in points:
                    abs_points.extend([px / 100.0 * orig_w, py / 100.0 * orig_h])

                xs = abs_points[0::2]
                ys = abs_points[1::2]
                x_min, x_max = min(xs), max(xs)
                y_min, y_max = min(ys), max(ys)
                bbox = [x_min, y_min, x_max - x_min, y_max - y_min]
                area = (x_max - x_min) * (y_max - y_min)

                coco["annotations"].append({
                    "id": ann_id,
                    "image_id": coco_image_id,
                    "category_id": LABEL_MAP[label],
                    "segmentation": [abs_points],
                    "bbox": bbox,
                    "area": area,
                    "iscrowd": 0,
                })
                ann_id += 1

    output_path = COCO_DIR / "annotations.json"
    with open(output_path, "w") as f:
        json.dump(coco, f, indent=2)

    print(f"Exported COCO annotations ({ann_id - 1} annotations, "
          f"{images_added} images) to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Export Label Studio annotations to YOLO and COCO formats"
    )
    parser.add_argument("--project-id", type=int, required=True, help="Label Studio project ID")
    parser.add_argument("--username", help="Label Studio login email")
    parser.add_argument("--password", help="Label Studio login password")
    parser.add_argument(
        "--format", choices=["yolo", "coco", "both"], default="both",
        help="Export format (default: both)",
    )
    args = parser.parse_args()

    if not (args.username and args.password):
        print("ERROR: Provide --username and --password.")
        sys.exit(1)

    print(f"Connecting to Label Studio at {LABEL_STUDIO_URL}...")
    session = get_session(LABEL_STUDIO_URL, args.username, args.password)

    tasks = get_tasks(session, LABEL_STUDIO_URL, args.project_id)
    if not tasks:
        print("No annotated tasks found. Annotate some images first.")
        return

    print(f"Found {len(tasks)} annotated tasks.")

    if args.format in ("yolo", "both"):
        export_yolo(tasks)
    if args.format in ("coco", "both"):
        export_coco(tasks)

    print("\nExport complete.")


if __name__ == "__main__":
    main()
