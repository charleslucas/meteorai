#!/usr/bin/env python3
"""
OpenCV frame picker — launched as a subprocess by the MeteorAI Streamlit app.

Controls
--------
  Space       Play / Pause
  C           Capture the current frame
  . or Right  Step forward  1 frame  (paused)
  , or Left   Step backward 1 frame  (paused)
  D           Jump forward  5 seconds
  A           Jump backward 5 seconds
  Q or Esc    Quit and write manifest

Usage
-----
  python youtube_picker.py --video PATH --output-dir PATH
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import cv2
except ImportError:
    print("ERROR: opencv-python not installed. Run: pip install opencv-python")
    sys.exit(1)

# Arrow key codes returned by cv2.waitKeyEx()
# Linux/macOS use X11 keysyms; Windows uses virtual-key codes
KEY_LEFT  = {65361, 2424832}   # left arrow
KEY_RIGHT = {65363, 2555904}   # right arrow


def fmt_time(seconds: float) -> str:
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m:02d}:{s:05.2f}"


def draw_overlay(frame, timestamp_s, frame_num, total_frames, captured_count, playing, flash):
    h, w = frame.shape[:2]
    out = frame.copy()

    # Dark banner at the bottom
    banner_h = 65
    cv2.rectangle(out, (0, h - banner_h), (w, h), (20, 20, 20), -1)
    cv2.line(out, (0, h - banner_h), (w, h - banner_h), (90, 90, 90), 1)

    state_str   = ">> PLAYING" if playing else "|| PAUSED "
    state_color = (80, 220, 80) if playing else (80, 220, 220)

    line1 = (f"{state_str}   {fmt_time(timestamp_s)}"
             f"   Frame {frame_num}/{total_frames}"
             f"   Captured: {captured_count}")
    cv2.putText(out, line1, (10, h - banner_h + 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.56, state_color, 1, cv2.LINE_AA)

    cv2.putText(out, "Space=Play/Pause  C=Capture  ,/.=Step  A/D=+-5s  Q=Quit",
                (10, h - banner_h + 52),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (170, 170, 170), 1, cv2.LINE_AA)

    # "CAPTURED!" flash
    if flash > 0:
        alpha = min(1.0, flash / 5.0)
        text = "CAPTURED!"
        scale, thick = 2.5, 4
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
        tx = (w - tw) // 2
        ty = (h - banner_h) // 2 + th // 2
        cv2.putText(out, text, (tx, ty),
                    cv2.FONT_HERSHEY_SIMPLEX, scale,
                    (0, int(255 * alpha), 0), thick, cv2.LINE_AA)

    return out


def seek_and_read(cap, target_frame):
    """Seek to target_frame index and return the frame."""
    cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
    ret, frame = cap.read()
    return frame if ret else None


def main():
    parser = argparse.ArgumentParser(description="MeteorAI OpenCV frame picker")
    parser.add_argument("--video",      required=True, help="Path to video file")
    parser.add_argument("--output-dir", required=True, help="Directory to save captured frames")
    args = parser.parse_args()

    video_path = Path(args.video)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"ERROR: Could not open video: {video_path}")
        sys.exit(1)

    fps          = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step_5s      = max(1, int(fps * 5))

    print(f"Video : {video_path.name}")
    print(f"FPS   : {fps:.2f}   Frames: {total_frames}   "
          f"Duration: {fmt_time(total_frames / fps)}")
    print(f"Output: {output_dir}")
    print()
    print("Controls: Space=Play/Pause  C=Capture  ,/.=Step  A/D=+-5s  Q/Esc=Quit")

    win = "MeteorAI Frame Picker — Q/Esc to quit"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, 1280, 720)

    # ---- state ----
    playing      = False
    flash        = 0
    captured     = []   # list of dicts written to manifest on exit
    frame_num    = 0    # index of the frame currently displayed

    ret, current = cap.read()
    if not ret:
        print("ERROR: Could not read first frame")
        cap.release()
        sys.exit(1)

    while True:
        # Advance one frame automatically when playing
        if playing:
            ret, new_frame = cap.read()
            if not ret:
                playing = False          # reached end of video
            else:
                frame_num = int(cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1
                current = new_frame

        timestamp_s = frame_num / fps
        display = draw_overlay(current.copy(), timestamp_s, frame_num,
                               total_frames, len(captured), playing, flash)
        if flash > 0:
            flash -= 1

        cv2.imshow(win, display)

        # Faster polling while playing so video feels smooth
        key = cv2.waitKeyEx(25 if playing else 50)

        if key == -1:
            continue

        plain = key & 0xFF

        # ── Quit ──────────────────────────────────────────────
        if plain in (ord('q'), ord('Q'), 27):   # 27 = Esc
            break

        # ── Play / Pause ───────────────────────────────────────
        elif plain == ord(' '):
            playing = not playing

        # ── Capture ───────────────────────────────────────────
        elif plain in (ord('c'), ord('C')):
            fname = f"frame_{frame_num:07d}_{timestamp_s:.2f}s.jpg"
            fpath = output_dir / fname
            h, w  = current.shape[:2]
            cv2.imwrite(str(fpath), current, [cv2.IMWRITE_JPEG_QUALITY, 95])
            captured.append({
                "frame_num":   frame_num,
                "timestamp_s": round(timestamp_s, 3),
                "filename":    fname,
                "width":       w,
                "height":      h,
            })
            flash = 10
            print(f"  Captured frame {frame_num:7d}  ({fmt_time(timestamp_s)})  "
                  f"-> {fname}  [{len(captured)} total]")

        # ── Step backward  (, or Left arrow) ──────────────────
        elif plain == ord(',') or key in KEY_LEFT:
            playing   = False
            target    = max(0, frame_num - 1)
            new_frame = seek_and_read(cap, target)
            if new_frame is not None:
                current   = new_frame
                frame_num = target

        # ── Step forward  (. or Right arrow) ─────────────────
        elif plain == ord('.') or key in KEY_RIGHT:
            playing = False
            ret, new_frame = cap.read()
            if ret:
                frame_num = int(cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1
                current   = new_frame

        # ── Jump backward 5 s  (A) ────────────────────────────
        elif plain in (ord('a'), ord('A')):
            target    = max(0, frame_num - step_5s)
            new_frame = seek_and_read(cap, target)
            if new_frame is not None:
                current   = new_frame
                frame_num = target

        # ── Jump forward 5 s  (D) ────────────────────────────
        elif plain in (ord('d'), ord('D')):
            target    = min(total_frames - 1, frame_num + step_5s)
            new_frame = seek_and_read(cap, target)
            if new_frame is not None:
                current   = new_frame
                frame_num = target

    # ── Cleanup ───────────────────────────────────────────────
    cap.release()
    cv2.destroyAllWindows()

    # Write manifest so Streamlit can read the results
    manifest = {"frames": captured}
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print(f"\nCaptured {len(captured)} frame(s).")
    print(f"Manifest written to: {manifest_path}")


if __name__ == "__main__":
    main()
