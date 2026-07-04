#!/usr/bin/env python3
"""
YOLOv8 ML Backend for Label Studio - MeteorAI

Serves real-time bounding box predictions from the trained YOLOv8 model.
Label Studio calls this backend each time a task is opened.

Usage:
    label-studio-ml start label_studio/yolo_backend.py --port 9091

Then in Label Studio: Settings -> Machine Learning -> Add Model -> http://localhost:9091

The model path is read from training/best_model.txt (same as auto_annotate.py).
Set YOLO_MODEL_PATH env var to override.
"""

import os
import sys
from pathlib import Path
from urllib.parse import unquote

import requests as http

from label_studio_ml.model import LabelStudioMLBase

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent
SCRAPER_DIR = PROJECT_DIR / "meteorite_scraper"
sys.path.insert(0, str(SCRAPER_DIR))

from dotenv import load_dotenv
load_dotenv(SCRAPER_DIR / ".env")

from config import IMAGES_DIR

LABEL_STUDIO_URL    = os.getenv("LABEL_STUDIO_URL", "http://localhost:8081")
LABEL_STUDIO_API_KEY = os.getenv("LABEL_STUDIO_API_KEY", "")

BEST_MODEL_PTR = PROJECT_DIR / "training" / "best_model.txt"
DEFAULT_MODEL  = PROJECT_DIR / "training" / "runs" / "meteorite_detector" / "weights" / "best.pt"

CONF_THRESHOLD = float(os.getenv("YOLO_CONF", "0.25"))

BBOX_FROM_NAME = "bbox"
TO_NAME        = "image"


def _resolve_model_path():
    override = os.getenv("YOLO_MODEL_PATH")
    if override:
        return Path(override)
    if BEST_MODEL_PTR.exists():
        p = Path(BEST_MODEL_PTR.read_text().strip())
        if p.exists():
            return p
    if DEFAULT_MODEL.exists():
        return DEFAULT_MODEL
    raise FileNotFoundError(
        "No trained model found. Run train_model.py first, or set YOLO_MODEL_PATH."
    )


def _image_path_from_task(task):
    """Return the local image Path for a Label Studio task, or None."""
    url = task.get("data", {}).get("image", "")
    # Local-files URL: /data/local-files/?d=<encoded_path>
    if "?d=" in url:
        encoded = url.split("?d=", 1)[1]
        local_path = unquote(encoded).replace("\\", "/")
        p = Path(local_path)
        if p.exists():
            return p
        # Try just the filename in IMAGES_DIR
        candidate = IMAGES_DIR / p.name
        if candidate.exists():
            return candidate
    # Fallback: try to download
    return None


class YOLOBackend(LabelStudioMLBase):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        from ultralytics import YOLO
        model_path = _resolve_model_path()
        print(f"[YOLOBackend] Loading model: {model_path}")
        self.model = YOLO(str(model_path))
        self.model_version = model_path.parent.parent.name
        print(f"[YOLOBackend] Classes: {self.model.names}")
        print(f"[YOLOBackend] Confidence threshold: {CONF_THRESHOLD}")

    def predict(self, tasks, **kwargs):
        predictions = []
        for task in tasks:
            img_path = _image_path_from_task(task)
            if img_path is None:
                predictions.append({"result": [], "score": 0.0, "model_version": self.model_version})
                continue

            results = self.model(str(img_path), conf=CONF_THRESHOLD, verbose=False)
            ls_results = []
            confidences = []

            for r in results:
                if r.boxes is None:
                    continue
                orig_w, orig_h = r.orig_shape[1], r.orig_shape[0]
                for box in r.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    conf = float(box.conf[0])
                    label = self.model.names[int(box.cls[0])]
                    ls_results.append({
                        "from_name": BBOX_FROM_NAME,
                        "to_name":   TO_NAME,
                        "type":      "rectanglelabels",
                        "score":     round(conf, 4),
                        "value": {
                            "x":               round(x1 / orig_w * 100.0, 4),
                            "y":               round(y1 / orig_h * 100.0, 4),
                            "width":           round((x2 - x1) / orig_w * 100.0, 4),
                            "height":          round((y2 - y1) / orig_h * 100.0, 4),
                            "rotation":        0,
                            "rectanglelabels": [label],
                        },
                    })
                    confidences.append(conf)

            score = sum(confidences) / len(confidences) if confidences else 0.0
            predictions.append({
                "result":        ls_results,
                "score":         round(score, 4),
                "model_version": self.model_version,
            })

        return predictions

    def fit(self, tasks, **kwargs):
        # Active learning / retraining hook — not implemented
        return {}


# ---------------------------------------------------------------------------
# Server entry point (when run directly)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    from label_studio_ml.api import init_app

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9091)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    model_dir = BACKEND_DIR / "yolo_model_dir"
    model_dir.mkdir(exist_ok=True)
    app = init_app(model_class=YOLOBackend, model_dir=str(model_dir))
    print(f"Starting YOLO ML backend on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)
