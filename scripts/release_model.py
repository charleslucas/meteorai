"""
Release a trained model from meteorai into the meteorite-detector-video submodule.

Copies best.pt (and optionally best_training_info.json) into
meteorite-detector-video/models/, commits and pushes the submodule,
then updates the parent repo's submodule reference.

Usage:
    python scripts/release_model.py
    python scripts/release_model.py --model training/runs/detect/train/weights/best.pt
    python scripts/release_model.py --tag v1.2
    python scripts/release_model.py --dry-run
"""

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


REPO_ROOT      = Path(__file__).resolve().parent.parent
SUBMODULE_DIR  = REPO_ROOT / "meteorite-detector-video"
MODELS_DIR     = SUBMODULE_DIR / "models"

# Where training artifacts land (ultralytics default)
DEFAULT_WEIGHTS = REPO_ROOT / "training" / "runs" / "detect" / "train" / "weights" / "best.pt"
# Fallback: a symlink/copy that release_model itself maintains
BEST_MODEL_LINK = REPO_ROOT / "training" / "best_model.txt"


def find_best_model(override=None):
    if override:
        p = Path(override)
        if not p.exists():
            sys.exit(f"ERROR: specified model not found: {p}")
        return p

    if DEFAULT_WEIGHTS.exists():
        return DEFAULT_WEIGHTS

    if BEST_MODEL_LINK.exists():
        ref = BEST_MODEL_LINK.read_text().strip()
        p = Path(ref) if Path(ref).is_absolute() else REPO_ROOT / ref
        if p.exists():
            return p
        sys.exit(f"ERROR: best_model.txt points to missing file: {p}")

    sys.exit(
        "ERROR: No trained model found.\n"
        f"Expected: {DEFAULT_WEIGHTS}\n"
        "Run a training job first, or specify --model <path>."
    )


def find_training_results():
    """Return the results.json or results.csv path if present."""
    base = DEFAULT_WEIGHTS.parent.parent  # .../train/
    for name in ("results.json", "results.csv"):
        p = base / name
        if p.exists():
            return p
    return None


def extract_map50(results_path):
    if results_path is None:
        return None
    if results_path.suffix == ".json":
        try:
            data = json.loads(results_path.read_text())
            # ultralytics results.json: list of per-epoch dicts
            if isinstance(data, list) and data:
                last = data[-1]
                return last.get("metrics/mAP50(B)") or last.get("mAP50")
        except Exception:
            pass
    if results_path.suffix == ".csv":
        try:
            lines = results_path.read_text().splitlines()
            header = [h.strip() for h in lines[0].split(",")]
            last   = [v.strip() for v in lines[-1].split(",")]
            row    = dict(zip(header, last))
            for key in ("metrics/mAP50(B)", "mAP50"):
                if key in row:
                    return float(row[key])
        except Exception:
            pass
    return None


def run(cmd, cwd=None, check=True, dry_run=False):
    label = " ".join(str(c) for c in cmd)
    if dry_run:
        print(f"  [dry-run] {label}")
        return
    print(f"  $ {label}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout.rstrip())
    if result.returncode != 0:
        print(result.stderr.rstrip(), file=sys.stderr)
        if check:
            sys.exit(f"Command failed (exit {result.returncode}): {label}")
    return result


def main():
    parser = argparse.ArgumentParser(description="Release a model into meteorite-detector-video")
    parser.add_argument("--model",   help="Path to .pt file (default: auto-detected)")
    parser.add_argument("--tag",     help="Version tag, e.g. v1.2 (default: auto from date)")
    parser.add_argument("--message", help="Commit message override")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen, do nothing")
    args = parser.parse_args()

    dry = args.dry_run

    # ------------------------------------------------------------------ #
    # 1. Locate model
    # ------------------------------------------------------------------ #
    model_src = find_best_model(args.model)
    print(f"Model source : {model_src}")

    # ------------------------------------------------------------------ #
    # 2. Gather metadata
    # ------------------------------------------------------------------ #
    now        = datetime.utcnow()
    tag        = args.tag or now.strftime("v%Y%m%d_%H%M")
    results_p  = find_training_results()
    map50      = extract_map50(results_p)

    meta = {
        "released_at": now.isoformat() + "Z",
        "tag":         tag,
        "source_model": str(model_src),
        "map50":       map50,
    }
    print(f"Tag          : {tag}")
    if map50 is not None:
        print(f"mAP50        : {map50:.4f}")

    # ------------------------------------------------------------------ #
    # 3. Verify submodule exists
    # ------------------------------------------------------------------ #
    if not SUBMODULE_DIR.exists():
        sys.exit(
            f"ERROR: submodule directory not found: {SUBMODULE_DIR}\n"
            "Run: git submodule update --init --recursive"
        )

    if not MODELS_DIR.exists():
        print(f"Creating {MODELS_DIR}")
        if not dry:
            MODELS_DIR.mkdir(parents=True)

    # ------------------------------------------------------------------ #
    # 4. Copy model and metadata
    # ------------------------------------------------------------------ #
    dest_pt   = MODELS_DIR / "best.pt"
    dest_meta = MODELS_DIR / "model_info.json"

    print(f"\nCopying {model_src.name} -> {dest_pt}")
    if not dry:
        shutil.copy2(model_src, dest_pt)

    print(f"Writing {dest_meta.name}")
    if not dry:
        dest_meta.write_text(json.dumps(meta, indent=2))

    # ------------------------------------------------------------------ #
    # 5. Commit and push submodule
    # ------------------------------------------------------------------ #
    commit_msg = args.message or f"Release model {tag}"
    if map50 is not None:
        commit_msg += f" (mAP50={map50:.3f})"

    print(f"\nCommitting submodule: {commit_msg}")
    run(["git", "add", "models/best.pt", "models/model_info.json"],
        cwd=SUBMODULE_DIR, dry_run=dry)
    run(["git", "commit", "-m", commit_msg],
        cwd=SUBMODULE_DIR, dry_run=dry)
    run(["git", "push"],
        cwd=SUBMODULE_DIR, dry_run=dry)

    # ------------------------------------------------------------------ #
    # 6. Tag the submodule release
    # ------------------------------------------------------------------ #
    print(f"Tagging submodule: {tag}")
    run(["git", "tag", tag], cwd=SUBMODULE_DIR, dry_run=dry)
    run(["git", "push", "origin", tag], cwd=SUBMODULE_DIR, dry_run=dry)

    # ------------------------------------------------------------------ #
    # 7. Update parent repo submodule reference
    # ------------------------------------------------------------------ #
    print("\nUpdating parent repo submodule reference...")
    run(["git", "add", "meteorite-detector-video"],
        cwd=REPO_ROOT, dry_run=dry)
    run(["git", "commit", "-m", f"Update meteorite-detector-video submodule to {tag}"],
        cwd=REPO_ROOT, dry_run=dry)

    print(f"\nDone. Model {tag} released into meteorite-detector-video.")
    if not dry:
        print(
            "\nNext steps:\n"
            "  1. Push the parent repo:  git push\n"
            "  2. Users update with:     git submodule update --remote"
        )


if __name__ == "__main__":
    main()
