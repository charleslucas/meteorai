"""
Minimal Label Studio API client for pushing tasks from the Streamlit app.

Configure via environment variables (or .env):
    LABEL_STUDIO_URL          default: http://localhost:8080
    LABEL_STUDIO_API_KEY      Legacy API token from Account & Settings
    LABEL_STUDIO_PROJECT_ID   Integer project ID (visible in the project URL)

If LABEL_STUDIO_API_KEY or LABEL_STUDIO_PROJECT_ID are not set, push_task()
is a silent no-op so the app works without Label Studio configured.
"""
import logging
import requests
from config import LABEL_STUDIO_URL, LABEL_STUDIO_API_KEY, LABEL_STUDIO_PROJECT_ID

logger = logging.getLogger(__name__)


def _session():
    s = requests.Session()
    prefix = "Bearer" if LABEL_STUDIO_API_KEY.startswith("eyJ") else "Token"
    s.headers.update({
        "Authorization": f"{prefix} {LABEL_STUDIO_API_KEY}",
        "Content-Type": "application/json",
    })
    return s


def push_task(record: dict) -> bool:
    """
    Push a single meteorite database record to Label Studio as a new task.

    Args:
        record: dict with at minimum 'stored_filename' and 'image_id' keys,
                as returned by db.get_meteorite_by_id() or built during insert.

    Returns:
        True on success, False on failure (errors are logged, not raised).
    """
    if not LABEL_STUDIO_API_KEY or not LABEL_STUDIO_PROJECT_ID:
        return False

    stored_filename = record.get("stored_filename", "")
    if not stored_filename:
        return False

    task = {
        "data": {
            "image":                   f"/data/local-files/?d=images/{stored_filename}",
            "image_id":                record.get("image_id"),
            "meteorite_name":          record.get("meteorite_name") or "Unknown",
            "primary_type":            record.get("primary_type") or "",
            "detailed_classification": record.get("detailed_classification") or "",
            "image_context":           record.get("image_context") or "",
            "mass_grams":              str(record["mass_grams"]) if record.get("mass_grams") else "",
        }
    }

    try:
        r = _session().post(
            f"{LABEL_STUDIO_URL.rstrip('/')}/api/projects/{LABEL_STUDIO_PROJECT_ID}/import",
            json=[task],
            timeout=10,
        )
        r.raise_for_status()
        logger.info(f"Pushed task for image_id={record.get('image_id')} to Label Studio.")
        return True
    except Exception as e:
        logger.warning(f"Label Studio push failed for {stored_filename}: {e}")
        return False
