#!/usr/bin/env python3
"""
MeteorAI Backup Export Script

Creates a timestamped ZIP archive containing:
  - Database schema SQL  (pg_dump --schema-only, for fresh installs)
  - Meteorite data JSON  (all rows, used for duplicate-safe merge imports)
  - Meteorite images
  - Label Studio annotations (native JSON, re-importable)
  - Environment config reference

Usage:
    python export_backup.py
    python export_backup.py --output backups/my_backup.zip
    python export_backup.py --ls-project-id 1 --ls-username your@email.com --ls-password yourpwd
    python export_backup.py --skip-label-studio
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, date, timezone
from decimal import Decimal
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_DIR = Path(__file__).resolve().parent
SCRAPER_DIR = PROJECT_DIR / "meteorite_scraper"
IMAGES_DIR = SCRAPER_DIR / "images"
ENV_FILE = SCRAPER_DIR / ".env"

sys.path.insert(0, str(SCRAPER_DIR))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_env(env_path: Path) -> dict:
    env = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def find_pg_dump() -> str:
    found = shutil.which("pg_dump")
    if found:
        return found
    for version in range(18, 13, -1):
        candidate = Path(f"C:/Program Files/PostgreSQL/{version}/bin/pg_dump.exe")
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError(
        "pg_dump not found. Add PostgreSQL bin directory to PATH, e.g.:\n"
        "  $env:PATH += ';C:\\Program Files\\PostgreSQL\\18\\bin'"
    )


def dump_schema(env: dict, output_sql: Path) -> None:
    """Export database schema only (no data) using pg_dump."""
    pg_dump = find_pg_dump()
    host = env.get("DB_HOST", "localhost")
    port = env.get("DB_PORT", "5432")
    user = env.get("DB_USER", "meteorite_user")
    dbname = env.get("DB_NAME", "meteorite_images")
    password = env.get("DB_PASSWORD", "")

    print(f"  Exporting schema for '{dbname}'...")
    env_vars = os.environ.copy()
    env_vars["PGPASSWORD"] = password

    result = subprocess.run(
        [pg_dump, "-h", host, "-p", port, "-U", user, "-d", dbname,
         "--no-password", "--schema-only", "--if-not-exists", "-f", str(output_sql)],
        env=env_vars,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pg_dump failed:\n{result.stderr}")
    print(f"  Schema saved ({output_sql.stat().st_size // 1024} KB).")


class JsonEncoder(json.JSONEncoder):
    """Handle types that aren't natively JSON-serialisable."""
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def export_data_json(env: dict, output_json: Path) -> int:
    """Export all meteorite rows to JSON for duplicate-safe import."""
    import psycopg2
    from psycopg2.extras import RealDictCursor

    conn = psycopg2.connect(
        host=env.get("DB_HOST", "localhost"),
        port=env.get("DB_PORT", "5432"),
        user=env.get("DB_USER", "meteorite_user"),
        password=env.get("DB_PASSWORD", ""),
        dbname=env.get("DB_NAME", "meteorite_images"),
    )
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM meteorites ORDER BY image_id")
            rows = [dict(r) for r in cur.fetchall()]
        # Also export scrape_logs if present
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM scrape_logs ORDER BY id")
                logs = [dict(r) for r in cur.fetchall()]
        except Exception:
            logs = []
    finally:
        conn.close()

    output_json.write_text(json.dumps({"meteorites": rows, "scrape_logs": logs},
                                      cls=JsonEncoder, indent=2))
    print(f"  Exported {len(rows)} meteorite records to JSON.")
    return len(rows)


def get_ls_session(base_url: str, username: str, password: str) -> requests.Session:
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
        raise Exception("Label Studio login failed. Check username and password.")
    r.raise_for_status()
    return session


def export_ls_annotations(base_url: str, project_id: int, session: requests.Session,
                           output_json: Path) -> int:
    print(f"  Exporting Label Studio project {project_id}...")
    r = session.get(f"{base_url}/api/projects/{project_id}/export",
                    params={"exportType": "JSON"})
    r.raise_for_status()
    tasks = r.json()

    r2 = session.get(f"{base_url}/api/projects/{project_id}")
    r2.raise_for_status()
    meta = r2.json()

    bundle = {
        "project_title": meta.get("title", "Meteorite Annotation"),
        "label_config": meta.get("label_config", ""),
        "tasks": tasks,
    }
    output_json.write_text(json.dumps(bundle, indent=2))
    annotated = sum(1 for t in tasks if t.get("annotations"))
    print(f"  Exported {len(tasks)} tasks ({annotated} annotated).")
    return len(tasks)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Export MeteorAI data to a ZIP backup")
    parser.add_argument("--output", help="Output ZIP path (default: meteorai_backup_TIMESTAMP.zip)")
    parser.add_argument("--ls-url", default="http://localhost:8080")
    parser.add_argument("--ls-project-id", type=int, help="Label Studio project ID to export")
    parser.add_argument("--ls-username", help="Label Studio login email")
    parser.add_argument("--ls-password", help="Label Studio login password")
    parser.add_argument("--skip-label-studio", action="store_true",
                        help="Skip Label Studio annotation export")
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(args.output) if args.output else PROJECT_DIR / f"meteorai_backup_{timestamp}.zip"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print("=== MeteorAI Backup Export ===")
    print(f"Output: {output_path}\n")

    env = load_env(ENV_FILE)
    if not env:
        print("WARNING: .env not found. Using default DB credentials.")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        # 1. Schema SQL
        print("[1/4] Exporting database schema...")
        schema_sql = tmp_dir / "schema.sql"
        try:
            dump_schema(env, schema_sql)
        except Exception as e:
            print(f"  ERROR: {e}")
            sys.exit(1)

        # 2. Data JSON
        print("[2/4] Exporting meteorite data...")
        data_json = tmp_dir / "data.json"
        try:
            record_count = export_data_json(env, data_json)
        except Exception as e:
            print(f"  ERROR exporting data: {e}")
            sys.exit(1)

        # 3. Label Studio
        ls_json = tmp_dir / "label_studio_annotations.json"
        ls_task_count = 0
        if args.skip_label_studio:
            print("[3/4] Skipping Label Studio export.")
        elif not args.ls_project_id:
            print("[3/4] Skipping Label Studio (no --ls-project-id). "
                  "Re-run with --ls-project-id N to include annotations.")
        elif not (args.ls_username and args.ls_password):
            print("[3/4] Skipping Label Studio (no --ls-username/--ls-password).")
        else:
            print(f"[3/4] Exporting Label Studio annotations from {args.ls_url}...")
            try:
                session = get_ls_session(args.ls_url, args.ls_username, args.ls_password)
                ls_task_count = export_ls_annotations(
                    args.ls_url, args.ls_project_id, session, ls_json)
            except Exception as e:
                print(f"  WARNING: Label Studio export failed: {e}")

        # 4. Build ZIP
        image_files = sorted(IMAGES_DIR.iterdir()) if IMAGES_DIR.exists() else []
        image_files = [f for f in image_files if f.is_file()]
        print(f"[4/4] Building ZIP archive ({len(image_files)} images)...")

        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "meteorai_version": "1.0",
            "database": {
                "host": env.get("DB_HOST", "localhost"),
                "name": env.get("DB_NAME", "meteorite_images"),
                "user": env.get("DB_USER", "meteorite_user"),
            },
            "record_count": record_count,
            "image_count": len(image_files),
            "label_studio_tasks": ls_task_count,
        }
        (tmp_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

        # Mask passwords in env reference
        env_ref = {k: ("***" if any(s in k.lower() for s in ("password", "secret", "key")) else v)
                   for k, v in env.items()}
        (tmp_dir / "env_reference.json").write_text(json.dumps(env_ref, indent=2))

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            zf.write(tmp_dir / "manifest.json", "manifest.json")
            zf.write(tmp_dir / "env_reference.json", "env_reference.json")
            zf.write(schema_sql, "schema.sql")
            zf.write(data_json, "data.json")
            if ls_json.exists():
                zf.write(ls_json, "label_studio_annotations.json")
            for img in image_files:
                zf.write(img, f"images/{img.name}")

        size_mb = output_path.stat().st_size / (1024 * 1024)
        print(f"\n=== Export Complete ===")
        print(f"  Archive:  {output_path}")
        print(f"  Size:     {size_mb:.1f} MB")
        print(f"  Records:  {record_count}")
        print(f"  Images:   {len(image_files)}")
        if ls_task_count:
            print(f"  LS tasks: {ls_task_count}")
        print(f"\nTo restore: python import_backup.py {output_path.name}")


if __name__ == "__main__":
    main()
