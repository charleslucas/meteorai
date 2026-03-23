# MeteorAI Training Guide

Training a YOLO model on annotated meteorite images to detect meteorites in drone video.

## Prerequisites

- Annotations completed in Label Studio (see [meteorite_scraper/README_SETUP.md](meteorite_scraper/README_SETUP.md))
- Ultralytics installed — stop Label Studio and the SAM backend first (their processes
  hold OpenCV loaded, which blocks the install), then run:
  ```bash
  pip install ultralytics
  ```

## 1. Export Annotations

You'll need your Label Studio API key: open Label Studio
On the left, go to **Organization**->**Api Token Settings** and enable Legacy Tokens
click your avatar (top right) → **Account & Settings** → **Legacy Token** → copy the token.

If you're not sure of your project ID, run the script with any ID and it will list all
available projects:

```bash
python label_studio/export_annotations.py --project-id 0 --api-key YOUR_API_KEY
```

Export to YOLO format (for bounding-box detection training):

```bash
python label_studio/export_annotations.py \
    --project-id YOUR_PROJECT_ID \
    --api-key YOUR_API_KEY \
    --format yolo
```

Export both YOLO and COCO at once (default):

```bash
python label_studio/export_annotations.py \
    --project-id YOUR_PROJECT_ID \
    --api-key YOUR_API_KEY
```

You can also set the key as an environment variable to avoid typing it each time:

```bash
set LABEL_STUDIO_API_KEY=YOUR_API_KEY
python label_studio/export_annotations.py --project-id YOUR_PROJECT_ID --format yolo
```

Exported files are saved to:
- `label_studio/exports/yolo/` — one `.txt` label file per image + `classes.txt`
- `label_studio/exports/coco/annotations.json` — COCO segmentation format

## 2. Organize the Dataset

YOLO expects images and labels split into train/val sets. Create this structure:

```
dataset/
  images/
    train/    ← ~80% of your meteorite images
    val/      ← ~20% of your meteorite images
  labels/
    train/    ← matching .txt label files
    val/
  dataset.yaml
```

With ~80 images, a reasonable split is 64 train / 16 val.

Create `dataset/dataset.yaml`:
```yaml
path: /absolute/path/to/dataset
train: images/train
val: images/val
names:
  0: meteorite
  1: fusion_crust
  2: regmaglypts
  3: metal_flake
  4: scale_reference
```

## 3. Train the Model

Starting from a pretrained YOLOv8 checkpoint gives you transfer learning, which is
essential when training on a small dataset (~80 images).

**Bounding box detection** (faster, recommended for real-time video):
```bash
yolo detect train data=dataset/dataset.yaml model=yolov8n.pt epochs=100 imgsz=640
```

**Instance segmentation** (more precise outlines, slower):
```bash
yolo segment train data=dataset/dataset.yaml model=yolov8n-seg.pt epochs=100 imgsz=640
```

Model size options (trade-off between speed and accuracy):
| Model       | Size  | Notes                              |
|-------------|-------|------------------------------------|
| yolov8n.pt  | Nano  | Fastest, smallest — good starting point |
| yolov8s.pt  | Small | Good balance                       |
| yolov8m.pt  | Medium| Better accuracy, slower            |
| yolov8l.pt  | Large | High accuracy, needs more VRAM     |

Training output is saved to `runs/detect/train/` (or `runs/segment/train/`).
The best weights are at `runs/detect/train/weights/best.pt`.

## 4. Evaluate the Model

After training, check metrics on the validation set:
```bash
yolo detect val data=dataset/dataset.yaml model=runs/detect/train/weights/best.pt
```

Key metrics to look at:
- **mAP50** — mean average precision at 50% IoU overlap (higher is better)
- **Precision** — how often detections are correct
- **Recall** — how many actual meteorites are detected

## 5. Run Inference on Drone Video

```bash
yolo detect predict \
    model=runs/detect/train/weights/best.pt \
    source=drone_footage.mp4 \
    conf=0.25
```

Output video with bounding boxes is saved to `runs/detect/predict/`.

Useful options:
```bash
# Save individual frames instead of video
yolo detect predict model=best.pt source=video.mp4 save_frames=True

# Adjust confidence threshold (lower = more detections, more false positives)
yolo detect predict model=best.pt source=video.mp4 conf=0.3

# Run on a folder of images
yolo detect predict model=best.pt source=path/to/frames/
```

## 6. Adding Video Frames to the Training Set

More training data — especially from the actual deployment environment (drone footage
or reference YouTube videos) — will significantly improve accuracy.

### From YouTube (recommended — built into the Streamlit app)

The Streamlit app has a built-in YouTube frame picker. Open the app, click **New Meteorite**,
paste a YouTube URL into the Image URL field, and follow the on-screen steps:

1. Download the video (saved to `meteorite_scraper/videos/`)
2. Navigate the video in the OpenCV frame picker window and press `C` to capture frames
3. Review the captured thumbnails in the browser and save selected frames to the database

Requires: `pip install yt-dlp opencv-python`

Frame picker controls:

| Key | Action |
|-----|--------|
| `Space` | Play / Pause |
| `C` | Capture current frame |
| `. / →` | Step forward 1 frame |
| `, / ←` | Step backward 1 frame |
| `D` | Jump forward 5 seconds |
| `A` | Jump backward 5 seconds |
| `Q / Esc` | Quit and return to browser |

### From local video files (ffmpeg)

For drone footage or other local video files not on YouTube:

```bash
# Extract 1 frame per second
ffmpeg -i drone_footage.mp4 -vf fps=1 meteorite_scraper/images/drone_%04d.jpg

# Extract 5 frames per second (for faster-moving footage)
ffmpeg -i drone_footage.mp4 -vf fps=5 meteorite_scraper/images/drone_%04d.jpg
```

Choose a frame rate that captures meaningful variation without too much redundancy
(consecutive frames are nearly identical and don't add training value).

Once frames are saved via the Streamlit app they are pushed to Label Studio automatically
(no manual sync needed). Annotate with SAM as normal, then re-export and retrain.

## Notes on Dataset Size

~80 images is a small training set. Expect the model to:
- Perform well on images similar to training data
- Struggle with new lighting conditions, angles, or backgrounds

Strategies to improve performance with limited data:
- **Annotate more images** — more data is the most effective improvement
- **Data augmentation** — Ultralytics applies this automatically (flips, rotations, color jitter)
- **Add drone footage frames** — domain-specific images will help generalize to the actual use case
- **Use a larger pretrained model** (yolov8s or yolov8m) — more capacity for fine details
