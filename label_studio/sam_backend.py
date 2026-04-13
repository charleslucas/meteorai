#!/usr/bin/env python3
"""
SAM ML Backend for Label Studio — MeteorAI

Provides automatic and interactive (smart-tool) pre-labeling using Meta's
Segment Anything Model (SAM 2, or SAM 1 as fallback).

Supports two modes:
  - Batch prediction: runs SAM's automatic mask generator on each image and
    returns the most prominent segment as a "meteorite" prediction.
  - Interactive prediction: when the user clicks with Label Studio's Smart
    tool, the click coordinates are used as a point prompt for SAM, returning
    a refined polygon around the clicked object.

Usage:
    label-studio-ml start label_studio/sam_backend.py --port 9090

Then in Label Studio: Settings → Model → Connect Model → http://localhost:9090
"""

import io
import os
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import numpy as np
import requests as http
import torch
from PIL import Image

from label_studio_ml.model import LabelStudioMLBase

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent
SCRAPER_DIR = PROJECT_DIR / "meteorite_scraper"
sys.path.insert(0, str(SCRAPER_DIR))

from dotenv import load_dotenv
load_dotenv(SCRAPER_DIR / ".env")

from config import IMAGES_DIR

# Default directory to look for model weights (alongside this file)
WEIGHTS_DIR = BACKEND_DIR / "sam_weights"

# Label Studio URL for downloading images when local path can't be resolved
LABEL_STUDIO_URL = os.getenv("LABEL_STUDIO_URL", "http://localhost:8080")
LABEL_STUDIO_API_KEY = os.getenv("LABEL_STUDIO_API_KEY", "")

# Labeling config names must match setup_project.py
BBOX_FROM_NAME = "bbox"
SEG_FROM_NAME = "segmentation"
TO_NAME = "image"

# Default label for single-object predictions
DEFAULT_LABEL = "meteorite"

# ---------------------------------------------------------------------------
# SAM loader — tries SAM 2 first, falls back to SAM 1
# ---------------------------------------------------------------------------

def _find_sam2_config(stem: str) -> str:
    """
    Dynamically locate the correct Hydra config YAML for a SAM 2 checkpoint
    by searching the installed sam2 package directory.

    Returns a path relative to the sam2 package root (e.g.
    'configs/sam2.1/sam2.1_hiera_large.yaml'), which is what build_sam2 expects
    when the Hydra search path is pkg://sam2.
    """
    import importlib.util
    spec = importlib.util.find_spec("sam2")
    if spec is None:
        raise ImportError("sam2 package not found")
    sam2_pkg_dir = Path(spec.origin).parent  # e.g. .../site-packages/sam2

    # Map checkpoint stem keywords → strings to look for in YAML filenames.
    # Prefer sam2.1 subdirectory (our download_sam_weights.py fetches SAM 2.1).
    size_keywords = {
        "large":     ["_l.", "_l_", "large"],
        "base_plus": ["b+", "base_plus"],
        "small":     ["_s.", "_s_", "small"],
        "tiny":      ["_t.", "_t_", "tiny"],
    }

    match_patterns = None
    for key, patterns in size_keywords.items():
        if key in stem:
            match_patterns = patterns
            break
    if match_patterns is None:
        match_patterns = [stem]  # fall back to full stem

    configs_root = sam2_pkg_dir / "configs"
    if not configs_root.exists():
        raise FileNotFoundError(
            f"No 'configs' directory found inside the sam2 package at {sam2_pkg_dir}. "
            f"Try reinstalling: pip install git+https://github.com/facebookresearch/sam2.git"
        )

    # Search sam2.1 first, then sam2
    for subdir in ["sam2.1", "sam2", ""]:
        search_dir = configs_root / subdir if subdir else configs_root
        if not search_dir.exists():
            continue
        for yaml_file in sorted(search_dir.glob("*.yaml")):
            if any(p in yaml_file.name for p in match_patterns):
                rel = yaml_file.relative_to(sam2_pkg_dir)
                return str(rel).replace("\\", "/")

    available = [str(p.relative_to(sam2_pkg_dir)) for p in configs_root.rglob("*.yaml")]
    raise FileNotFoundError(
        f"No SAM 2 config found for checkpoint '{stem}'. "
        f"Available configs: {available}"
    )


def _load_sam2(weights_dir: Path, device: str):
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor
    from sam2.automatic_mask_generator import SAM2AutomaticMaskGenerator

    # Prefer small over tiny for quality; user can override with SAM_MODEL env var
    model_name = os.getenv("SAM_MODEL", "sam2_hiera_small")
    checkpoint = weights_dir / f"{model_name}.pt"
    if not checkpoint.exists():
        # Try any .pt file in the directory
        candidates = sorted(weights_dir.glob("sam2*.pt"))
        if not candidates:
            raise FileNotFoundError(
                f"No SAM 2 checkpoint found in {weights_dir}.\n"
                f"Run: python label_studio/download_sam_weights.py"
            )
        checkpoint = candidates[0]

    stem = checkpoint.stem  # e.g. "sam2_hiera_large"
    cfg_name = _find_sam2_config(stem)
    print(f"  Loading SAM 2 model: {checkpoint.name} (config: {cfg_name}) on {device}")
    model = build_sam2(cfg_name, str(checkpoint), device=device)
    predictor = SAM2ImagePredictor(model)
    mask_gen = SAM2AutomaticMaskGenerator(
        model,
        points_per_side=16,        # fewer points = faster on CPU
        pred_iou_thresh=0.82,
        stability_score_thresh=0.90,
        min_mask_region_area=500,  # ignore tiny fragments
    )
    return predictor, mask_gen, 2


def _load_sam1(weights_dir: Path, device: str):
    from segment_anything import sam_model_registry, SamPredictor, SamAutomaticMaskGenerator

    model_name = os.getenv("SAM_MODEL", "vit_b")
    fname_map = {
        "vit_h": "sam_vit_h_4b8939.pth",
        "vit_l": "sam_vit_l_0b3195.pth",
        "vit_b": "sam_vit_b_01ec64.pth",
    }
    checkpoint = weights_dir / fname_map.get(model_name, fname_map["vit_b"])
    if not checkpoint.exists():
        candidates = sorted(weights_dir.glob("sam_vit_*.pth"))
        if not candidates:
            raise FileNotFoundError(
                f"No SAM 1 checkpoint found in {weights_dir}.\n"
                f"Run: python label_studio/download_sam_weights.py"
            )
        checkpoint = candidates[0]

    print(f"  Loading SAM 1 model: {checkpoint.name} on {device}")
    sam = sam_model_registry[checkpoint.stem[:5]](checkpoint=str(checkpoint))
    sam.to(device=device)
    predictor = SamPredictor(sam)
    mask_gen = SamAutomaticMaskGenerator(
        sam,
        points_per_side=16,
        pred_iou_thresh=0.82,
        stability_score_thresh=0.90,
        min_mask_region_area=500,
    )
    return predictor, mask_gen, 1


# ---------------------------------------------------------------------------
# Mask utilities
# ---------------------------------------------------------------------------

def _mask_to_polygon(mask: np.ndarray, W: int, H: int,
                     simplify_eps: float = 0.005) -> list:
    """Convert binary mask to a polygon as [[x_pct, y_pct], ...] list."""
    try:
        import cv2
        contours, _ = cv2.findContours(
            mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            return []
        contour = max(contours, key=cv2.contourArea)
        eps = simplify_eps * cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, eps, True)
        return [[float(p[0][0] / W * 100), float(p[0][1] / H * 100)]
                for p in approx]
    except ImportError:
        # Fallback: use skimage if cv2 not available
        from skimage import measure
        contours = measure.find_contours(mask.astype(float), 0.5)
        if not contours:
            return []
        contour = max(contours, key=len)
        # Downsample to ~60 points max
        step = max(1, len(contour) // 60)
        return [[float(c[1] / W * 100), float(c[0] / H * 100)]
                for c in contour[::step]]


def _mask_to_bbox(mask: np.ndarray, W: int, H: int) -> dict:
    """Convert binary mask to bounding box as {x, y, width, height} (pct)."""
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    y1, y2 = np.where(rows)[0][[0, -1]]
    x1, x2 = np.where(cols)[0][[0, -1]]
    return {
        "x": float(x1 / W * 100),
        "y": float(y1 / H * 100),
        "width": float((x2 - x1) / W * 100),
        "height": float((y2 - y1) / H * 100),
    }


def _select_best_mask(masks: list, H: int, W: int) -> dict | None:
    """
    From SAM's automatic masks, select the best candidate for the main
    meteorite subject using simple heuristics:
      - Area between 3% and 65% of image area
      - Closest centroid to image centre
      - Highest stability score among top candidates
    """
    total = H * W
    cx, cy = W / 2, H / 2
    candidates = []

    for m in masks:
        area_frac = m["area"] / total
        if not (0.03 <= area_frac <= 0.65):
            continue
        # Centroid from bbox
        bb = m["bbox"]  # [x, y, w, h]  (pixel coords)
        mcx = bb[0] + bb[2] / 2
        mcy = bb[1] + bb[3] / 2
        dist = ((mcx - cx) ** 2 + (mcy - cy) ** 2) ** 0.5
        score = m.get("stability_score", 0) + m.get("predicted_iou", 0)
        candidates.append((dist, -score, m))

    if not candidates:
        return None

    # Sort: prefer central, high-quality masks
    candidates.sort(key=lambda t: (t[0], t[1]))
    return candidates[0][2]


# ---------------------------------------------------------------------------
# Label Studio result builders
# ---------------------------------------------------------------------------

def _polygon_result(points: list, label: str, W: int, H: int, score: float) -> dict:
    return {
        "from_name": SEG_FROM_NAME,
        "to_name": TO_NAME,
        "type": "polygonlabels",
        "score": score,
        "original_width": W,
        "original_height": H,
        "value": {
            "points": points,
            "polygonlabels": [label],
            "closed": True,
        },
    }


def _bbox_result(bbox: dict, label: str, W: int, H: int, score: float) -> dict:
    return {
        "from_name": BBOX_FROM_NAME,
        "to_name": TO_NAME,
        "type": "rectanglelabels",
        "score": score,
        "original_width": W,
        "original_height": H,
        "value": {**bbox, "rectanglelabels": [label]},
    }


# ---------------------------------------------------------------------------
# Backend class
# ---------------------------------------------------------------------------

class SAMMeteoriteBackend(LabelStudioMLBase):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Ensure setup() was called — some label-studio-ml versions don't call
        # it automatically on the instance used for prediction.
        if not hasattr(self, 'mask_gen'):
            self.setup()

    def get_model_version(self):
        """Return a static version string so the framework doesn't try to look
        up a numeric job-ID result (which only exists when fit() is used)."""
        return f"SAM{self.sam_version or 2}-meteorite"

    def setup(self):
        """Load SAM model on startup."""
        self.predictor = None
        self.mask_gen = None
        self.sam_version = None

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"SAM backend: using device={self.device}")

        WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            self.predictor, self.mask_gen, self.sam_version = _load_sam2(
                WEIGHTS_DIR, self.device
            )
        except Exception as e:
            print(f"  SAM 2 unavailable ({type(e).__name__}: {e}), trying SAM 1...")
            try:
                self.predictor, self.mask_gen, self.sam_version = _load_sam1(
                    WEIGHTS_DIR, self.device
                )
            except Exception as e2:
                print(f"  SAM 1 also unavailable ({type(e2).__name__}: {e2})")
                print("  ERROR: No SAM model could be loaded. Check installation.")
                return

        print(f"  SAM {self.sam_version} loaded successfully.")

    # ------------------------------------------------------------------
    # Image loading
    # ------------------------------------------------------------------

    def _load_image(self, image_url: str) -> np.ndarray:
        """Resolve a Label Studio image URL to an RGB numpy array."""
        # Try to load directly from disk first (fastest)
        if "?d=" in image_url:
            # URL is like /data/local-files/?d=images/foo.jpg — strip the images/ prefix
            d_param = image_url.split("?d=")[-1]
            filename = Path(d_param).name
            local_path = IMAGES_DIR / filename
            if local_path.exists():
                print(f"  Loading image from disk: {local_path}")
                return np.array(Image.open(local_path).convert("RGB"))

        # Fall back to HTTP download (handles absolute URLs with host)
        if image_url.startswith("/"):
            image_url = LABEL_STUDIO_URL.rstrip("/") + image_url

        headers = {}
        if LABEL_STUDIO_API_KEY:
            headers["Authorization"] = f"Token {LABEL_STUDIO_API_KEY}"

        r = http.get(image_url, headers=headers, timeout=30)
        r.raise_for_status()
        return np.array(Image.open(io.BytesIO(r.content)).convert("RGB"))

    # ------------------------------------------------------------------
    # Prompt extraction from Label Studio context
    # ------------------------------------------------------------------

    def _extract_prompts(self, context: dict | None, W: int, H: int) -> dict:
        """
        Extract point or rectangle prompts from Label Studio's interactive
        annotation context (sent when user clicks with the Smart tool).

        Returns: {"points": [...], "labels": [...], "box": [...] or None}
        """
        prompts = {"points": [], "labels": [], "box": None}
        if not context:
            return prompts

        annotation = context.get("annotation", {})
        results = annotation.get("result", [])

        for r in results:
            rtype = r.get("type", "")
            val = r.get("value", {})

            if rtype == "keypointlabels":
                # Point click: convert from pct to pixel coords
                px = val.get("x", 50) / 100 * W
                py = val.get("y", 50) / 100 * H
                prompts["points"].append([px, py])
                prompts["labels"].append(1)  # foreground

            elif rtype == "rectanglelabels":
                # Rough rectangle drawn by user
                x1 = val.get("x", 0) / 100 * W
                y1 = val.get("y", 0) / 100 * H
                x2 = x1 + val.get("width", 10) / 100 * W
                y2 = y1 + val.get("height", 10) / 100 * H
                prompts["box"] = np.array([x1, y1, x2, y2])

        return prompts

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def _run_prompted(self, image: np.ndarray, prompts: dict,
                      label: str) -> list:
        """Run SAM with explicit point/box prompts (interactive mode)."""
        H, W = image.shape[:2]
        self.predictor.set_image(image)

        kwargs = {}
        if prompts["points"]:
            kwargs["point_coords"] = np.array(prompts["points"])
            kwargs["point_labels"] = np.array(prompts["labels"])
        if prompts["box"] is not None:
            kwargs["box"] = prompts["box"]
        if not kwargs:
            return []

        masks, scores, _ = self.predictor.predict(
            multimask_output=True, **kwargs
        )
        # Use the highest-confidence mask
        best_idx = int(np.argmax(scores))
        mask = masks[best_idx]
        score = float(scores[best_idx])

        results = []
        polygon = _mask_to_polygon(mask, W, H)
        if polygon:
            results.append(_polygon_result(polygon, label, W, H, score))
        bbox = _mask_to_bbox(mask, W, H)
        results.append(_bbox_result(bbox, label, W, H, score))
        return results

    def _run_automatic(self, image: np.ndarray) -> list:
        """Run SAM automatic mask generator and select best meteorite candidate."""
        H, W = image.shape[:2]
        masks = self.mask_gen.generate(image)

        best = _select_best_mask(masks, H, W)
        if best is None:
            return []

        mask = best["segmentation"]
        score = float(
            (best.get("stability_score", 0) + best.get("predicted_iou", 0)) / 2
        )

        results = []
        polygon = _mask_to_polygon(mask, W, H)
        if polygon:
            results.append(_polygon_result(polygon, DEFAULT_LABEL, W, H, score))
        bbox = _mask_to_bbox(mask, W, H)
        results.append(_bbox_result(bbox, DEFAULT_LABEL, W, H, score))
        return results

    # ------------------------------------------------------------------
    # LabelStudioMLBase entry point
    # ------------------------------------------------------------------

    def predict(self, tasks, context=None, **kwargs):
        predictions = []

        if self.mask_gen is None:
            print("  ERROR: SAM model not loaded — check startup errors above.")
            return [{"result": [], "score": 0} for _ in tasks]

        for task in tasks:
            image_url = task.get("data", {}).get("image", "")
            print(f"  predict called: image_url={image_url!r}", flush=True)
            if not image_url:
                print("  No image URL in task data.", flush=True)
                predictions.append({"result": [], "score": 0})
                continue

            try:
                image = self._load_image(image_url)
                print(f"  Image loaded: shape={image.shape}", flush=True)
            except Exception as e:
                print(f"  Could not load image '{image_url}': {e}", flush=True)
                predictions.append({"result": [], "score": 0})
                continue

            H, W = image.shape[:2]
            prompts = self._extract_prompts(context, W, H)
            has_prompts = bool(prompts["points"] or prompts["box"] is not None)

            # Determine label from context (which label the user had selected)
            label = DEFAULT_LABEL
            if context:
                ann = context.get("annotation", {})
                for r in ann.get("result", []):
                    for key in ("keypointlabels", "rectanglelabels", "polygonlabels"):
                        labels = r.get("value", {}).get(key, [])
                        if labels:
                            label = labels[0]
                            break

            if has_prompts:
                result = self._run_prompted(image, prompts, label)
                mode = "interactive"
            else:
                result = self._run_automatic(image)
                mode = "automatic"

            score = result[0].get("score", 0) if result else 0
            print(f"  [{mode}] {Path(image_url).name}: "
                  f"{len(result)} annotations, score={score:.2f}", flush=True)
            predictions.append({
                "result": result,
                "score": score,
                "model_version": f"SAM{self.sam_version}",
            })

        return predictions


# ---------------------------------------------------------------------------
# Server entry point (when run directly)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    from label_studio_ml.api import init_app

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9090)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    model_dir = BACKEND_DIR / "model_dir"
    model_dir.mkdir(exist_ok=True)
    app = init_app(model_class=SAMMeteoriteBackend, model_dir=str(model_dir))
    print(f"Starting SAM ML backend on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)
