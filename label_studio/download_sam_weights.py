#!/usr/bin/env python3
"""
Download SAM model weights into label_studio/sam_weights/.

Usage:
    python label_studio/download_sam_weights.py              # SAM 2 small (default)
    python label_studio/download_sam_weights.py --model tiny # SAM 2 tiny (fastest/smallest)
    python label_studio/download_sam_weights.py --model large # SAM 2 large (best quality)
    python label_studio/download_sam_weights.py --sam1       # SAM 1 vit_b instead

Model sizes and approximate GPU memory requirements:
  SAM 2 tiny:        ~39 MB   — good for CPU, ~2 GB VRAM
  SAM 2 small:       ~46 MB   — recommended, ~2.5 GB VRAM
  SAM 2 base_plus:   ~80 MB   — ~3.5 GB VRAM
  SAM 2 large:      ~224 MB   — ~7 GB VRAM
  SAM 1 vit_b:      ~375 MB   — 2 GB VRAM
"""

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

WEIGHTS_DIR = Path(__file__).resolve().parent / "sam_weights"

SAM2_MODELS = {
    "tiny":      ("sam2_hiera_tiny.pt",
                  "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_tiny.pt"),
    "small":     ("sam2_hiera_small.pt",
                  "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_small.pt"),
    "base_plus": ("sam2_hiera_base_plus.pt",
                  "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_base_plus.pt"),
    "large":     ("sam2_hiera_large.pt",
                  "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_large.pt"),
}

SAM1_MODELS = {
    "vit_b": ("sam_vit_b_01ec64.pth",
               "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth"),
    "vit_l": ("sam_vit_l_0b3195.pth",
               "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_l_0b3195.pth"),
    "vit_h": ("sam_vit_h_4b8939.pth",
               "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth"),
}


def download(url: str, dest: Path) -> None:
    if dest.exists():
        print(f"  Already downloaded: {dest.name}")
        return

    print(f"  Downloading {dest.name}...")
    print(f"  URL: {url}")

    def _progress(block_count, block_size, total_size):
        downloaded = block_count * block_size
        if total_size > 0:
            pct = min(100, downloaded * 100 // total_size)
            mb = downloaded / (1024 * 1024)
            total_mb = total_size / (1024 * 1024)
            print(f"\r  {pct:3d}%  {mb:.1f} / {total_mb:.1f} MB", end="", flush=True)

    try:
        urllib.request.urlretrieve(url, dest, reporthook=_progress)
        print()  # newline after progress
        size_mb = dest.stat().st_size / (1024 * 1024)
        print(f"  Saved: {dest} ({size_mb:.1f} MB)")
    except Exception as e:
        if dest.exists():
            dest.unlink()
        raise RuntimeError(f"Download failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Download SAM model weights")
    parser.add_argument("--model", default="small",
                        choices=list(SAM2_MODELS) + list(SAM1_MODELS),
                        help="Model variant (default: small)")
    parser.add_argument("--sam1", action="store_true",
                        help="Download SAM 1 instead of SAM 2")
    args = parser.parse_args()

    WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Weights directory: {WEIGHTS_DIR}\n")

    if args.sam1:
        model_key = args.model if args.model in SAM1_MODELS else "vit_b"
        filename, url = SAM1_MODELS[model_key]
        print(f"Downloading SAM 1 {model_key}...")
    else:
        model_key = args.model if args.model in SAM2_MODELS else "small"
        filename, url = SAM2_MODELS[model_key]
        print(f"Downloading SAM 2 {model_key}...")

    download(url, WEIGHTS_DIR / filename)

    print("\nDone. Next steps:")
    print("  1. Start the SAM backend:  .\\label_studio\\start_sam_backend.bat")
    print("  2. Or use the full startup: .\\start_services.bat")
    print("  3. In Label Studio: Settings → Model → Connect → http://localhost:9090")
    if not args.sam1:
        print(f"\nSet SAM_MODEL={Path(filename).stem} in the environment if using")
        print("a non-default model name.")


if __name__ == "__main__":
    main()
