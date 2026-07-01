#!/usr/bin/env python3
"""
MeteorAI Backup Import Script

Safely merges a backup ZIP (from export_backup.py) into an existing or fresh installation.
Duplicate records are detected and skipped — existing data is never overwritten or deleted.

Deduplication keys:
  - Meteorite records:  source_url  (or stored_filename when source_url is absent)
  - Images:             filename    (skipped if file already exists at destination)
  - Label Studio tasks: stored_filename in task data (skipped if task already exists)

Usage:
    python import_backup.py meteorai_backup_20250101_120000.zip
    python import_backup.py backup.zip --ls-username your@email.com --ls-password yourpwd
    python import_backup.py backup.zip --skip-label-studio
    python import_backup.py backup.zip --db-password mypassword --pg-superuser postgres
"""

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

import requests

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_DIR = Path(__file__).resolve().parent
SCRAPER_DIR = PROJECT_DIR / "meteorite_scraper"
IMAGES_DIR  = SCRAPER_DIR / "images"
VIDEOS_DIR  = SCRAPER_DIR / "videos"
ENV_FILE    = SCRAPER_DIR / ".env"

# Columns to insert (excludes image_id and created_at — let the DB assign these)
METEORITE_COLUMNS = [
    "meteorite_name", "original_filename", "stored_filename",
    "source_url", "page_url", "photo_page_url", "file_format", "file_size_bytes",
    "width_px", "height_px", "primary_type", "secondary_type",
    "detailed_classification", "mass_grams", "fall_or_find",
    "discovery_date", "discovery_location", "discovery_latitude",
    "discovery_longitude", "terrain_type", "image_context",
    "viewing_angle", "background_type", "lighting_type",
    "license", "photographer", "needs_review", "notes",
    # Columns added in later migrations — included if present in the backup row
    "in_situ", "from_drone", "sectioned", "parent_url", "photo_quality",
]

# ---------------------------------------------------------------------------
# PostgreSQL helpers
# ---------------------------------------------------------------------------

def find_pg_binary(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    for version in range(18, 13, -1):
        candidate = Path(f"C:/Program Files/PostgreSQL/{version}/bin/{name}.exe")
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError(
        f"'{name}' not found. Add PostgreSQL bin dir to PATH:\n"
        f"  $env:PATH += ';C:\\Program Files\\PostgreSQL\\18\\bin'"
    )


def run_psql(args_list: list, password: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PGPASSWORD"] = password
    return subprocess.run(args_list, env=env, capture_output=True, text=True)


def pg_query(host, port, superuser, superuser_pw, sql, dbname="postgres") -> str:
    psql = find_pg_binary("psql")
    r = run_psql([psql, "-h", host, "-p", port, "-U", superuser,
                  "-tAc", sql, dbname], superuser_pw)
    return r.stdout.strip()


def ensure_db_and_user(host, port, superuser, superuser_pw, dbname, username, db_password):
    """Create the DB user and database if they don't already exist."""
    psql = find_pg_binary("psql")

    # Create user
    exists = pg_query(host, port, superuser, superuser_pw,
                      f"SELECT 1 FROM pg_roles WHERE rolname='{username}'")
    if exists == "1":
        print(f"  User '{username}' already exists — updating password.")
        run_psql([psql, "-h", host, "-p", port, "-U", superuser, "postgres",
                  "-c", f"ALTER USER {username} WITH PASSWORD '{db_password}';"],
                 superuser_pw)
    else:
        print(f"  Creating user '{username}'...")
        r = run_psql([psql, "-h", host, "-p", port, "-U", superuser, "postgres",
                      "-c", f"CREATE USER {username} WITH PASSWORD '{db_password}';"],
                     superuser_pw)
        if r.returncode != 0:
            raise RuntimeError(f"Failed to create user: {r.stderr}")

    # Create database
    exists = pg_query(host, port, superuser, superuser_pw,
                      f"SELECT 1 FROM pg_database WHERE datname='{dbname}'")
    if exists == "1":
        print(f"  Database '{dbname}' already exists — will merge data.")
        return False  # existing DB
    else:
        print(f"  Creating database '{dbname}'...")
        r = run_psql([psql, "-h", host, "-p", port, "-U", superuser, "postgres",
                      "-c", f"CREATE DATABASE {dbname} OWNER {username};"],
                     superuser_pw)
        if r.returncode != 0:
            raise RuntimeError(f"Failed to create database: {r.stderr}")
        run_psql([psql, "-h", host, "-p", port, "-U", superuser, "postgres",
                  "-c", f"GRANT ALL PRIVILEGES ON DATABASE {dbname} TO {username};"],
                 superuser_pw)
        return True  # new DB


def apply_schema(host, port, username, db_password, dbname, schema_sql: Path):
    """Apply schema SQL. Uses IF NOT EXISTS so it is safe on existing databases."""
    psql = find_pg_binary("psql")
    print(f"  Applying schema ({schema_sql.stat().st_size // 1024} KB)...")
    # ON_ERROR_STOP=0 so 'already exists' notices don't abort the whole run
    r = run_psql([psql, "-h", host, "-p", port, "-U", username, "-d", dbname,
                  "-f", str(schema_sql)], db_password)
    # pg_dump --if-not-exists means tables won't error; still log anything unusual
    errors = [l for l in r.stderr.splitlines()
              if "ERROR" in l and "already exists" not in l]
    if errors:
        print("  Schema warnings:\n  " + "\n  ".join(errors[:5]))
    print("  Schema applied.")


# ---------------------------------------------------------------------------
# Data merge helpers
# ---------------------------------------------------------------------------

def get_existing_source_urls(conn) -> set:
    with conn.cursor() as cur:
        cur.execute("SELECT source_url FROM meteorites WHERE source_url IS NOT NULL")
        return {row[0] for row in cur.fetchall()}


def get_existing_stored_filenames(conn) -> set:
    with conn.cursor() as cur:
        cur.execute("SELECT stored_filename FROM meteorites WHERE stored_filename IS NOT NULL")
        return {row[0] for row in cur.fetchall()}


def get_filename_to_imageid_map(conn) -> dict:
    """Return {stored_filename: image_id} for all records in the target DB."""
    with conn.cursor() as cur:
        cur.execute("SELECT stored_filename, image_id FROM meteorites "
                    "WHERE stored_filename IS NOT NULL")
        return {row[0]: row[1] for row in cur.fetchall()}


def merge_meteorite_rows(conn, rows: list) -> tuple[int, int]:
    """Insert rows not already present. Returns (inserted, skipped)."""
    existing_urls = get_existing_source_urls(conn)
    existing_filenames = get_existing_stored_filenames(conn)

    inserted = skipped = 0

    # Find which columns actually exist in the DB
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'meteorites'
        """)
        db_columns = {row[0] for row in cur.fetchall()}

    cols = [c for c in METEORITE_COLUMNS if c in db_columns]
    placeholders = ", ".join(["%s"] * len(cols))
    col_list = ", ".join(cols)
    insert_sql = f"INSERT INTO meteorites ({col_list}) VALUES ({placeholders})"

    with conn.cursor() as cur:
        for row in rows:
            src_url = row.get("source_url") or ""
            stored_fn = row.get("stored_filename") or ""

            # Dedup check: source_url takes priority, fall back to stored_filename
            if src_url and src_url in existing_urls:
                skipped += 1
                continue
            if not src_url and stored_fn and stored_fn in existing_filenames:
                skipped += 1
                continue

            values = [row.get(c) for c in cols]
            try:
                cur.execute(insert_sql, values)
                if src_url:
                    existing_urls.add(src_url)
                if stored_fn:
                    existing_filenames.add(stored_fn)
                inserted += 1
            except Exception as e:
                print(f"  WARNING: Could not insert row '{stored_fn}': {e}")
                conn.rollback()
                # Re-fetch existing sets after rollback
                existing_urls = get_existing_source_urls(conn)
                existing_filenames = get_existing_stored_filenames(conn)

    conn.commit()
    return inserted, skipped


# ---------------------------------------------------------------------------
# Label Studio helpers
# ---------------------------------------------------------------------------

def get_ls_session(base_url, username=None, password=None, api_key=None) -> requests.Session:
    if api_key:
        session = requests.Session()
        prefix = "Bearer" if api_key.startswith("eyJ") else "Token"
        session.headers.update({
            "Authorization": f"{prefix} {api_key}",
            "Content-Type": "application/json",
        })
        return session
    session = requests.Session()
    r = session.get(f"{base_url}/user/login")
    r.raise_for_status()
    csrf = session.cookies.get("csrftoken", "")
    r = session.post(f"{base_url}/user/login", data={
        "email": username,
        "password": password,
        "csrfmiddlewaretoken": csrf,
    }, headers={"Referer": f"{base_url}/user/login"})
    r.raise_for_status()
    csrf = session.cookies.get("csrftoken", csrf)
    session.headers.update({"Content-Type": "application/json", "X-CSRFToken": csrf})
    r = session.get(f"{base_url}/api/projects")
    if r.status_code in (401, 403):
        raise Exception("Label Studio login failed.")
    r.raise_for_status()
    return session


def get_existing_ls_filenames(base_url: str, project_id: int,
                               session: requests.Session) -> set:
    """Return set of stored_filenames that already have tasks in the LS project."""
    filenames = set()
    page = 1
    while True:
        r = session.get(f"{base_url}/api/tasks",
                        params={"project": project_id, "page": page, "page_size": 200})
        if r.status_code == 404:
            break
        r.raise_for_status()
        data = r.json()
        tasks = data.get("tasks", data) if isinstance(data, dict) else data
        if not tasks:
            break
        for t in tasks:
            fn = t.get("data", {}).get("stored_filename") or ""
            if fn:
                filenames.add(fn)
        if isinstance(data, dict) and not data.get("next"):
            break
        page += 1
    return filenames


def import_ls_annotations(base_url: str, session: requests.Session,
                           bundle_path: Path, filename_to_id: dict,
                           project_id: int = None):
    """
    Import Label Studio tasks, patching image_id to match the target DB and
    skipping tasks that have no corresponding DB record (orphans) or already
    exist in the LS project.

    filename_to_id: {stored_filename: image_id} from the TARGET database.
    """
    bundle = json.loads(bundle_path.read_text())
    title = bundle.get("project_title", "Meteorite Annotation")
    label_config = bundle.get("label_config", "")
    tasks = bundle.get("tasks", [])

    if not tasks:
        print("  No tasks found in annotation export.")
        return

    # Use existing project or create a new one
    if project_id:
        print(f"  Using existing Label Studio project {project_id}.")
        pid = project_id
    else:
        print(f"  Creating Label Studio project '{title}'...")
        r = session.post(f"{base_url}/api/projects",
                         json={"title": title, "label_config": label_config})
        r.raise_for_status()
        pid = r.json()["id"]
        print(f"  Created project ID: {pid}")

        # Configure local file storage
        images_path = str(IMAGES_DIR.resolve()).replace("\\", "/")
        try:
            session.post(f"{base_url}/api/storages/localfiles", json={
                "project": pid,
                "path": images_path,
                "title": "Meteorite Images",
                "use_blob_urls": True,
            }).raise_for_status()
            print(f"  Local storage: {images_path}")
        except Exception as e:
            print(f"  WARNING: Could not configure local storage: {e}")

    # Dedup: skip tasks whose stored_filename already exists in the project
    existing_ls = get_existing_ls_filenames(base_url, pid, session)
    print(f"  Project already has {len(existing_ls)} tasks — checking for duplicates...")

    new_tasks = []
    skipped_dup = skipped_orphan = 0
    for t in tasks:
        fn = t.get("data", {}).get("stored_filename") or ""

        # Skip if already in LS project
        if fn and fn in existing_ls:
            skipped_dup += 1
            continue

        # Skip if no matching DB record (orphan — image was not imported or was deleted)
        if fn and fn not in filename_to_id:
            skipped_orphan += 1
            continue

        # Patch image_id to use the target DB's ID for this stored_filename
        if fn and fn in filename_to_id:
            t = dict(t)  # shallow copy so we don't mutate the original
            t["data"] = dict(t["data"])
            t["data"]["image_id"] = filename_to_id[fn]

        new_tasks.append(t)

    if skipped_dup:
        print(f"  Skipped {skipped_dup} tasks already in Label Studio.")
    if skipped_orphan:
        print(f"  Skipped {skipped_orphan} orphan tasks (no matching DB record).")

    if not new_tasks:
        print(f"  Nothing new to import into Label Studio.")
        return

    # Import in batches — strip to only the fields LS accepts (newer versions
    # reject the full export format containing db_predictions / comment_authors).
    imported = 0
    batch_size = 100
    for i in range(0, len(new_tasks), batch_size):
        batch = [{"data": t["data"], "annotations": t.get("annotations", [])}
                 for t in new_tasks[i:i + batch_size]]
        r = session.post(f"{base_url}/api/projects/{pid}/import", json=batch)
        r.raise_for_status()
        imported += r.json().get("task_count", len(batch))

    annotated = sum(1 for t in new_tasks if t.get("annotations"))
    print(f"  Imported {imported} tasks ({annotated} annotated).")
    print(f"  Open: {base_url}/projects/{pid}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Merge a MeteorAI backup ZIP into an existing or fresh installation"
    )
    parser.add_argument("backup", help="Path to the backup ZIP file")

    # Database
    parser.add_argument("--db-host", default="localhost")
    parser.add_argument("--db-port", default="5432")
    parser.add_argument("--db-name", default="meteorite_images")
    parser.add_argument("--db-user", default="meteorite_user")
    parser.add_argument("--db-password", default=None,
                        help="App DB user password (prompted if omitted)")
    parser.add_argument("--pg-superuser", default="postgres",
                        help="PostgreSQL superuser for creating DB/user (default: postgres)")
    parser.add_argument("--pg-superuser-password", default=None,
                        help="Superuser password (prompted if omitted)")

    # Label Studio
    parser.add_argument("--ls-url", default=None, help="Label Studio base URL")
    parser.add_argument("--ls-project-id", type=int, default=None,
                        help="Import into an existing LS project (creates new project if omitted)")
    parser.add_argument("--ls-api-key", default=None,
                        help="Label Studio legacy API token (overrides .env)")
    parser.add_argument("--ls-username", help="Label Studio login email (alternative to --ls-api-key)")
    parser.add_argument("--ls-password", help="Label Studio login password (alternative to --ls-api-key)")
    parser.add_argument("--skip-label-studio", action="store_true")

    # Images / Videos
    parser.add_argument("--images-dir", default=None,
                        help="Override target images directory")
    parser.add_argument("--videos-dir", default=None,
                        help="Override target videos directory")
    parser.add_argument("--skip-videos", action="store_true",
                        help="Skip restoring downloaded YouTube videos")
    args = parser.parse_args()

    backup_path = Path(args.backup)
    if not backup_path.exists():
        print(f"ERROR: Backup file not found: {backup_path}")
        sys.exit(1)

    target_images = Path(args.images_dir) if args.images_dir else IMAGES_DIR
    target_videos = Path(args.videos_dir) if args.videos_dir else VIDEOS_DIR

    # Fill Label Studio defaults from .env when not provided on the command line
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    ls_url      = args.ls_url or env.get("LABEL_STUDIO_URL", "http://localhost:8080")
    ls_api_key  = args.ls_api_key or env.get("LABEL_STUDIO_API_KEY", "")
    ls_username = args.ls_username
    ls_password = args.ls_password

    print("=== MeteorAI Backup Import ===")
    print(f"Backup: {backup_path}")
    print("Existing data will be preserved — only new records are added.\n")

    with zipfile.ZipFile(backup_path, "r") as zf:
        names = set(zf.namelist())

        if "manifest.json" in names:
            manifest = json.loads(zf.read("manifest.json"))
            print(f"Backup created: {manifest.get('created_at', 'unknown')}")
            print(f"Records in backup: {manifest.get('record_count', '?')}")
            print(f"Images in backup:  {manifest.get('image_count', '?')}")
            if manifest.get('video_count'):
                print(f"Videos in backup:  {manifest['video_count']}")
            if manifest.get('label_studio_tasks'):
                print(f"LS tasks in backup: {manifest['label_studio_tasks']}")
            print()

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            zf.extractall(tmp_dir)

            schema_sql = tmp_dir / "schema.sql"
            data_json = tmp_dir / "data.json"
            ls_json = tmp_dir / "label_studio_annotations.json"

            # --- Prompt for passwords ---
            db_password = args.db_password or getpass.getpass(
                f"Password for DB user '{args.db_user}': "
            )
            pg_super_password = args.pg_superuser_password or getpass.getpass(
                f"Password for PostgreSQL superuser '{args.pg_superuser}': "
            )

            # --- 1. Database setup ---
            print("[1/3] Setting up database...")
            try:
                is_new_db = ensure_db_and_user(
                    args.db_host, args.db_port,
                    args.pg_superuser, pg_super_password,
                    args.db_name, args.db_user, db_password,
                )
            except Exception as e:
                print(f"  ERROR: {e}")
                sys.exit(1)

            # Apply schema (safe with IF NOT EXISTS)
            if schema_sql.exists():
                apply_schema(args.db_host, args.db_port,
                             args.db_user, db_password, args.db_name, schema_sql)
            else:
                print("  WARNING: schema.sql not found in backup (old format?).")

            # Merge meteorite data and build filename→image_id map for LS linkage
            filename_to_id = {}
            if data_json.exists():
                print("  Merging meteorite records...")
                bundle = json.loads(data_json.read_text())
                rows = bundle.get("meteorites", [])
                conn = psycopg2.connect(
                    host=args.db_host, port=args.db_port,
                    user=args.db_user, password=db_password,
                    dbname=args.db_name,
                )
                try:
                    inserted, skipped = merge_meteorite_rows(conn, rows)
                    # Build map AFTER merge so it reflects the target DB's IDs
                    filename_to_id = get_filename_to_imageid_map(conn)
                finally:
                    conn.close()
                print(f"  Records: {inserted} inserted, {skipped} skipped (duplicates).")
                print(f"  DB now has {len(filename_to_id)} total records.")
            else:
                print("  WARNING: data.json not found in backup.")

            # Write .env
            env_content = (
                f"DB_HOST={args.db_host}\n"
                f"DB_NAME={args.db_name}\n"
                f"DB_USER={args.db_user}\n"
                f"DB_PASSWORD={db_password}\n"
                f"DB_PORT={args.db_port}\n"
            )
            ENV_FILE.write_text(env_content)
            print(f"  Written: {ENV_FILE}")

            # --- 2. Images ---
            print(f"\n[2/4] Copying images to {target_images}...")
            target_images.mkdir(parents=True, exist_ok=True)
            image_names = [n for n in names if n.startswith("images/") and not n.endswith("/")]
            copied = skipped_imgs = 0
            for name in image_names:
                dst = target_images / Path(name).name
                if dst.exists():
                    skipped_imgs += 1
                    continue
                shutil.copy2(tmp_dir / name, dst)
                copied += 1
            print(f"  Images: {copied} copied, {skipped_imgs} skipped (already exist).")

            # --- 3. Videos ---
            video_names = [n for n in names if n.startswith("videos/") and not n.endswith("/")]
            if args.skip_videos or not video_names:
                if video_names and args.skip_videos:
                    print(f"\n[3/4] Skipping {len(video_names)} video(s) (--skip-videos).")
                else:
                    print(f"\n[3/4] No videos in this backup.")
            else:
                print(f"\n[3/4] Copying {len(video_names)} video(s) to {target_videos}...")
                target_videos.mkdir(parents=True, exist_ok=True)
                copied_vids = skipped_vids = 0
                for name in video_names:
                    dst = target_videos / Path(name).name
                    if dst.exists():
                        skipped_vids += 1
                        continue
                    shutil.copy2(tmp_dir / name, dst)
                    copied_vids += 1
                print(f"  Videos: {copied_vids} copied, {skipped_vids} skipped (already exist).")

            # --- 4. Label Studio ---
            if args.skip_label_studio:
                print("\n[4/4] Skipping Label Studio import.")
            elif not ls_json.exists():
                print("\n[4/4] No Label Studio annotations in this backup.")
            elif not (ls_api_key or (ls_username and ls_password)):
                print("\n[4/4] Skipping Label Studio (no credentials provided).")
                print("       Set LABEL_STUDIO_API_KEY in .env or use --ls-api-key / --ls-username.")
            else:
                print(f"\n[4/4] Importing Label Studio annotations into {ls_url}...")
                try:
                    session = get_ls_session(ls_url, ls_username, ls_password, ls_api_key)
                    import_ls_annotations(ls_url, session, ls_json,
                                          filename_to_id, args.ls_project_id)
                except Exception as e:
                    print(f"  WARNING: Label Studio import failed: {e}")

    print("\n=== Import Complete ===")
    print("Next steps:")
    print("  1. Start services:  .\\start_services.bat")
    print("  2. Streamlit app:   http://localhost:8501")
    if not args.skip_label_studio and ls_json.exists():
        print("  3. Label Studio:    http://localhost:8080")


if __name__ == "__main__":
    main()
