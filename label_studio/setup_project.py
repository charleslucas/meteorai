#!/usr/bin/env python3
"""
Set up a Label Studio project for meteorite image annotation.

Usage:
    1. Start Label Studio with local file serving enabled (via start_services.bat).

    2. Open http://localhost:8080, create an account, copy API key from Account & Settings.

    3. Run this script:
       python label_studio/setup_project.py --api-key YOUR_API_KEY
"""
import argparse
import os
import sys
from pathlib import Path

import requests

# Add meteorite_scraper to path so we can import its modules
SCRAPER_DIR = Path(__file__).resolve().parent.parent / "meteorite_scraper"
sys.path.insert(0, str(SCRAPER_DIR))

from database import DatabaseManager
from config import IMAGES_DIR

LABEL_STUDIO_URL = os.getenv("LABEL_STUDIO_URL", "http://localhost:8080")

LABELING_CONFIG = """<View>
  <Header value="Meteorite Annotation"/>
  <Image name="image" value="$image" zoom="true" zoomControl="true" rotateControl="true"/>

  <Header value="Bounding Box Detection"/>
  <RectangleLabels name="bbox" toName="image">
    <Label value="meteorite" background="#FF0000"/>
    <Label value="fusion_crust" background="#00FF00"/>
    <Label value="regmaglypts" background="#0000FF"/>
    <Label value="metal_flake" background="#FFD700"/>
    <Label value="scale_reference" background="#FF69B4"/>
  </RectangleLabels>

  <Header value="Segmentation (Polygon)"/>
  <PolygonLabels name="segmentation" toName="image">
    <Label value="meteorite" background="#FF0000"/>
    <Label value="fusion_crust" background="#00FF00"/>
    <Label value="regmaglypts" background="#0000FF"/>
    <Label value="metal_flake" background="#FFD700"/>
    <Label value="scale_reference" background="#FF69B4"/>
  </PolygonLabels>
</View>"""


class LabelStudioClient:
    """Simple Label Studio API client using requests directly."""

    def __init__(self, url, session):
        self.url = url.rstrip("/")
        self.session = session

    @classmethod
    def from_credentials(cls, url, username, password):
        """Log in with username/password and return an authenticated client."""
        base_url = url.rstrip("/")
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})

        # Get CSRF token from login page
        r = session.get(f"{base_url}/user/login")
        r.raise_for_status()
        csrf = session.cookies.get("csrftoken", "")

        # Log in with form post
        session.headers.pop("Content-Type", None)
        r = session.post(f"{base_url}/user/login", data={
            "email": username,
            "password": password,
            "csrfmiddlewaretoken": csrf,
        }, headers={"Referer": f"{base_url}/user/login"})
        r.raise_for_status()

        # Update CSRF token from post-login cookies and set for API calls
        csrf = session.cookies.get("csrftoken", csrf)
        session.headers.update({
            "Content-Type": "application/json",
            "X-CSRFToken": csrf,
        })

        # Verify login by hitting the projects API
        r = session.get(f"{base_url}/api/projects")
        if r.status_code == 403 or r.status_code == 401:
            raise Exception(f"Login failed (status {r.status_code}). Check your username and password.")
        r.raise_for_status()
        print(f"Logged in successfully as {username}.")
        return cls(base_url, session)

    @classmethod
    def from_api_key(cls, url, api_key):
        """Authenticate with an API token."""
        base_url = url.rstrip("/")
        session = requests.Session()
        prefix = "Bearer" if api_key.startswith("eyJ") else "Token"
        session.headers.update({
            "Authorization": f"{prefix} {api_key}",
            "Content-Type": "application/json",
        })
        return cls(base_url, session)

    def check_connection(self):
        r = self.session.get(f"{self.url}/api/projects")
        if r.status_code == 401:
            raise Exception(f"Authentication failed (401). Response: {r.text}")
        r.raise_for_status()

    def create_project(self, title, label_config):
        r = self.session.post(f"{self.url}/api/projects", json={
            "title": title,
            "label_config": label_config,
        })
        r.raise_for_status()
        return r.json()

    def create_local_storage(self, project_id, path, title):
        r = self.session.post(f"{self.url}/api/storages/localfiles", json={
            "project": project_id,
            "path": path,
            "title": title,
            "use_blob_urls": True,
        })
        r.raise_for_status()
        return r.json()

    def import_tasks(self, project_id, tasks):
        r = self.session.post(
            f"{self.url}/api/projects/{project_id}/import",
            json=tasks,
        )
        r.raise_for_status()
        return r.json()


def main():
    parser = argparse.ArgumentParser(
        description="Set up a Label Studio project for meteorite annotation"
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("LABEL_STUDIO_API_KEY"),
        help="Label Studio API token (or set LABEL_STUDIO_API_KEY env var)",
    )
    parser.add_argument("--username", help="Label Studio login email (alternative to --api-key)")
    parser.add_argument("--password", help="Label Studio login password (alternative to --api-key)")
    parser.add_argument(
        "--project-name",
        default="Meteorite Annotation",
        help="Name for the Label Studio project",
    )
    args = parser.parse_args()

    # 1. Connect
    print(f"Connecting to Label Studio at {LABEL_STUDIO_URL}...")
    if args.username and args.password:
        ls = LabelStudioClient.from_credentials(LABEL_STUDIO_URL, args.username, args.password)
    elif args.api_key:
        ls = LabelStudioClient.from_api_key(LABEL_STUDIO_URL, args.api_key)
    else:
        print("ERROR: Provide either --api-key or both --username and --password.")
        sys.exit(1)
    ls.check_connection()
    print("Connected successfully.")

    # 2. Create project
    project = ls.create_project(args.project_name, LABELING_CONFIG)
    project_id = project["id"]
    print(f"Created project '{args.project_name}' (ID: {project_id})")

    # 3. Configure local file storage
    images_path = str(IMAGES_DIR.resolve()).replace("\\", "/")
    ls.create_local_storage(project_id, images_path, "Meteorite Images")
    print(f"Connected local storage: {images_path}")

    # 4. Build tasks from database
    print("Querying meteorite database...")
    db = DatabaseManager()
    records = db.get_all_meteorites(limit=10000, offset=0)
    print(f"Found {len(records)} meteorite records.")

    tasks = []
    for rec in records:
        tasks.append({
            "data": {
                "image": f"/data/local-files/?d={rec['stored_filename']}",
                "image_id": rec["image_id"],
                "meteorite_name": rec.get("meteorite_name") or "Unknown",
                "primary_type": rec.get("primary_type") or "",
                "detailed_classification": rec.get("detailed_classification") or "",
                "image_context": rec.get("image_context") or "",
                "mass_grams": str(rec["mass_grams"]) if rec.get("mass_grams") else "",
            }
        })

    # 5. Import tasks
    result = ls.import_tasks(project_id, tasks)
    print(f"Imported {result.get('task_count', len(tasks))} tasks into project {project_id}.")
    print(f"\nOpen Label Studio at: {LABEL_STUDIO_URL}/projects/{project_id}")
    print("You can now begin annotating meteorite images.")


if __name__ == "__main__":
    main()
