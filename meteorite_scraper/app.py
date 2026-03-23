import streamlit as st
import sys
import os
import json
import hashlib
import re
import shutil
import subprocess
import requests
import io
from pathlib import Path

# Add the meteorite_scraper directory to path so imports work
sys.path.insert(0, str(Path(__file__).parent))

from database import DatabaseManager
from config import IMAGES_DIR, METADATA_DIR, SCRAPE_CONFIG, VIDEOS_DIR
from label_studio_client import push_task as ls_push_task
from utils import generate_filename, validate_image, save_metadata_json

try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except ImportError:
    YT_DLP_AVAILABLE = False

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

# Staging directory for captured frames (sits alongside images/ and videos/)
YT_STAGING_DIR = Path(__file__).parent / "yt_staging"

db = DatabaseManager()

st.set_page_config(page_title="Meteorite Browser", layout="wide")
st.title("Meteorite Browser")

# Custom CSS for red delete buttons
st.markdown("""
<style>
    .row-delete button {
        background-color: #d32f2f !important;
        color: white !important;
        border: none !important;
    }
    .row-delete button:hover {
        background-color: #b71c1c !important;
        color: white !important;
    }
</style>
""", unsafe_allow_html=True)

# --- Sidebar Filters ---
st.sidebar.header("Filters")

name_search = st.sidebar.text_input("Search by name")

# Populate filter dropdowns
try:
    primary_types = ["All"] + db.get_distinct_values("primary_type")
except Exception:
    primary_types = ["All"]

try:
    image_contexts = ["All"] + db.get_distinct_values("image_context")
except Exception:
    image_contexts = ["All"]

filter_in_situ = st.sidebar.checkbox("In Situ only")
selected_type = st.sidebar.selectbox("Primary type", primary_types)
selected_context = st.sidebar.selectbox("Image context", image_contexts)
filter_needs_review = st.sidebar.checkbox("Needs review only")

# Build filters dict
filters = {}
if name_search:
    filters['meteorite_name'] = name_search
if filter_in_situ:
    filters['in_situ'] = True
if selected_type != "All":
    filters['primary_type'] = selected_type
if selected_context != "All":
    filters['image_context'] = selected_context
if filter_needs_review:
    filters['needs_review'] = True

# --- Session state ---
if 'view' not in st.session_state:
    st.session_state.view = 'browse'
if 'selected_id' not in st.session_state:
    st.session_state.selected_id = None
if 'confirm_delete' not in st.session_state:
    st.session_state.confirm_delete = False
if 'page' not in st.session_state:
    st.session_state.page = 0
if 'list_confirm_delete' not in st.session_state:
    st.session_state.list_confirm_delete = None

# YouTube picker state
for _key in ('yt_url', 'yt_metadata', 'yt_stage', 'yt_video_path',
             'yt_video_info', 'yt_process', 'yt_captured_frames'):
    if _key not in st.session_state:
        st.session_state[_key] = None

PAGE_SIZE = 25


# ---------------------------------------------------------------------------
# YouTube helpers
# ---------------------------------------------------------------------------

def is_youtube_url(url):
    """Return True if url looks like a YouTube video link."""
    if not url:
        return False
    return bool(re.match(
        r'https?://(www\.|m\.)?(youtube\.com/(watch|shorts|embed)|youtu\.be/)',
        url.strip()
    ))


def _clear_yt_staging():
    if YT_STAGING_DIR.exists():
        shutil.rmtree(str(YT_STAGING_DIR), ignore_errors=True)


def _reset_yt_state():
    _clear_yt_staging()
    st.session_state.yt_url = None
    st.session_state.yt_metadata = None
    st.session_state.yt_stage = None
    st.session_state.yt_video_path = None
    st.session_state.yt_video_info = None
    st.session_state.yt_process = None
    st.session_state.yt_captured_frames = None
    # Clear per-frame checkboxes
    for k in [k for k in st.session_state if k.startswith('yt_keep_')]:
        del st.session_state[k]


def _do_download(url):
    """Download a YouTube video to VIDEOS_DIR and store info in session state."""
    VIDEOS_DIR.mkdir(exist_ok=True)
    ydl_opts = {
        # Prefer a pre-merged mp4/webm so ffmpeg is not required.
        # Falls back to bestvideo+bestaudio only if ffmpeg is available.
        'format': 'best[ext=mp4]/best[ext=webm]/best',
        'outtmpl': str(VIDEOS_DIR / '%(id)s.%(ext)s'),
        'quiet': True,
        'noplaylist': True,
    }
    with st.spinner("Downloading video from YouTube..."):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
            video_id = info['id']
            video_path = next(
                (f for f in VIDEOS_DIR.iterdir() if f.stem == video_id), None
            )
            if not video_path:
                st.error("Download finished but could not locate the video file.")
                return
            st.session_state.yt_video_path = str(video_path)
            st.session_state.yt_video_info = {
                'id':       info.get('id', ''),
                'title':    info.get('title', 'Unknown'),
                'uploader': info.get('uploader', ''),
                'duration': info.get('duration', 0),
            }
            st.session_state.yt_stage = 'downloaded'
        except Exception as e:
            st.error(f"Download failed: {e}")


def _do_launch_picker():
    """Launch the OpenCV frame picker as a non-blocking subprocess."""
    _clear_yt_staging()
    YT_STAGING_DIR.mkdir(parents=True, exist_ok=True)
    picker = Path(__file__).parent / "youtube_picker.py"
    proc = subprocess.Popen(
        [sys.executable, str(picker),
         '--video',      st.session_state.yt_video_path,
         '--output-dir', str(YT_STAGING_DIR)],
    )
    st.session_state.yt_process = proc
    st.session_state.yt_stage = 'picker_running'


def _load_captured_frames():
    """Read manifest.json written by the picker and store results in session state."""
    manifest_path = YT_STAGING_DIR / "manifest.json"
    if not manifest_path.exists():
        st.session_state.yt_captured_frames = []
        return
    data = json.loads(manifest_path.read_text())
    frames = data.get('frames', [])
    for f in frames:
        f['path'] = str(YT_STAGING_DIR / f['filename'])
    st.session_state.yt_captured_frames = frames
    st.session_state.yt_stage = 'frames_ready'
    # Default: all frames selected
    for i in range(len(frames)):
        if f'yt_keep_{i}' not in st.session_state:
            st.session_state[f'yt_keep_{i}'] = True


def _save_yt_frames(captured, metadata):
    """Copy selected frames to IMAGES_DIR and insert database records."""
    url        = st.session_state.yt_url or ''
    video_info = st.session_state.yt_video_info or {}
    meteorite_name = metadata.get('meteorite_name') or 'Unknown'

    to_save = [f for i, f in enumerate(captured)
               if st.session_state.get(f'yt_keep_{i}', True)]

    if not to_save:
        st.warning("No frames selected to save.")
        return

    inserted = 0
    errors   = 0

    with st.spinner(f"Saving {len(to_save)} frame(s)..."):
        for frame in to_save:
            ts         = frame['timestamp_s']
            source_url = f"{url}#t={ts:.3f}"

            if db.url_exists(source_url):
                continue

            video_id   = video_info.get('id', 'unknown')
            short_hash = hashlib.md5(f"{video_id}_{ts:.3f}".encode()).hexdigest()[:8]
            safe_name  = re.sub(r'[^\w\s-]', '_', meteorite_name)[:30].strip()
            dest_name  = f"yt_{safe_name}_{short_hash}.jpg"
            dest_path  = IMAGES_DIR / dest_name

            src_path = Path(frame.get('path', ''))
            if not src_path.exists():
                st.error(f"Missing frame file: {src_path.name}")
                errors += 1
                continue

            shutil.copy2(str(src_path), str(dest_path))

            db_data = {
                'meteorite_name':          meteorite_name or None,
                'original_filename':       frame['filename'],
                'stored_filename':         dest_name,
                'source_url':              source_url,
                'page_url':                url,
                'photo_page_url':          None,
                'file_format':             'jpg',
                'file_size_bytes':         dest_path.stat().st_size,
                'width_px':                frame.get('width', 0),
                'height_px':               frame.get('height', 0),
                'primary_type':            metadata.get('primary_type') or None,
                'secondary_type':          metadata.get('secondary_type') or None,
                'detailed_classification': metadata.get('detailed_classification') or None,
                'mass_grams':              metadata.get('mass_grams'),
                'fall_or_find':            metadata.get('fall_or_find') or None,
                'discovery_date':          None,
                'discovery_location':      metadata.get('discovery_location') or None,
                'discovery_latitude':      metadata.get('discovery_latitude'),
                'discovery_longitude':     metadata.get('discovery_longitude'),
                'terrain_type':            metadata.get('terrain_type') or None,
                'image_context':           metadata.get('image_context') or 'video_frame',
                'viewing_angle':           metadata.get('viewing_angle') or None,
                'background_type':         metadata.get('background_type') or None,
                'lighting_type':           metadata.get('lighting_type') or None,
                'license':                 None,
                'photographer':            video_info.get('uploader') or None,
                'needs_review':            metadata.get('needs_review', True),
                'notes': (metadata.get('notes') or
                          f"YouTube: {video_info.get('title', '')} t={ts:.2f}s"),
            }

            try:
                image_id = db.insert_meteorite(db_data)
                extra = {
                    'in_situ':              metadata.get('in_situ', False),
                    'from_drone':           metadata.get('from_drone', False),
                    'sectioned':            metadata.get('sectioned', False),
                    'fusion_crust_present': metadata.get('fusion_crust_present', False),
                    'regmaglypts_present':  metadata.get('regmaglypts_present', False),
                    'visible_metal':        metadata.get('visible_metal', False),
                    'parent_url':           metadata.get('parent_url') or None,
                }
                if metadata.get('photo_quality'):
                    extra['photo_quality'] = metadata['photo_quality']
                if metadata.get('weathering_grade'):
                    extra['weathering_grade'] = metadata['weathering_grade']
                db.update_meteorite(image_id, extra)
                ls_push_task({**db_data, 'image_id': image_id})
                inserted += 1
            except Exception as e:
                st.error(f"DB error saving frame: {e}")
                dest_path.unlink(missing_ok=True)
                errors += 1

    _clear_yt_staging()

    if inserted > 0:
        st.success(f"Saved {inserted} frame(s) to database!")
        _reset_yt_state()
        st.session_state.view = 'browse'
        st.rerun()
    elif errors:
        st.error("All saves failed — check the errors above.")


def show_youtube_picker_view():
    """Multi-stage view: download → launch picker → review frames → save."""
    if st.button("< Back to New Meteorite"):
        _reset_yt_state()
        st.session_state.view = 'add_new'
        st.rerun()

    st.subheader("YouTube Frame Picker")

    url      = st.session_state.yt_url or ''
    metadata = st.session_state.yt_metadata or {}
    stage    = st.session_state.yt_stage   # None | 'downloaded' | 'picker_running' | 'frames_ready'

    st.write(f"**URL:** {url}")
    if metadata.get('meteorite_name'):
        st.write(f"**Meteorite:** {metadata['meteorite_name']}")
    st.divider()

    # ── Stage 1: Download ────────────────────────────────────────────────────
    if stage is None:
        if not YT_DLP_AVAILABLE:
            st.error("yt-dlp not installed. Run: `pip install yt-dlp`")
            return
        st.markdown("**Step 1 of 3 — Download video**")
        st.caption(f"Video will be saved to: `{VIDEOS_DIR}`")
        if st.button("Download Video", type="primary"):
            _do_download(url)
            st.rerun()

    # ── Stage 2: Launch picker ───────────────────────────────────────────────
    elif stage == 'downloaded':
        if not CV2_AVAILABLE:
            st.error("opencv-python not installed. Run: `pip install opencv-python`")
            return
        info     = st.session_state.yt_video_info or {}
        title    = info.get('title', 'Unknown')
        uploader = info.get('uploader', '')
        dur      = info.get('duration', 0) or 0
        st.success(
            f"Downloaded: **{title}**"
            + (f" by {uploader}" if uploader else '')
            + f"  ({int(dur)//60}m {int(dur)%60}s)"
        )
        st.caption(f"Saved to: `{st.session_state.yt_video_path}`")
        st.markdown("**Step 2 of 3 — Pick frames**")
        st.markdown("A separate window will open. Use the controls below to navigate and capture frames.")
        st.markdown("""
| Key | Action |
|-----|--------|
| **Space** | Capture current frame |
| **P** | Play / Pause |
| **. / →** | Step forward 1 frame |
| **, / ←** | Step backward 1 frame |
| **D** | Jump forward 5 seconds |
| **A** | Jump backward 5 seconds |
| **Q / Esc** | Quit and return here |
""")
        if st.button("Launch Frame Picker Window", type="primary"):
            _do_launch_picker()
            st.rerun()

    # ── Stage 3: Picker running ──────────────────────────────────────────────
    elif stage == 'picker_running':
        proc = st.session_state.yt_process
        # Auto-detect if the process has already exited
        if proc and proc.poll() is not None:
            _load_captured_frames()
            st.rerun()

        st.info("**Frame picker window is open.** Capture frames, then close the window (Q/Esc).")
        st.markdown("""
| Key | Action |
|-----|--------|
| **Space** | Capture current frame |
| **P** | Play / Pause |
| **. / →** | Step forward 1 frame |
| **, / ←** | Step backward 1 frame |
| **D** | Jump forward 5 seconds |
| **A** | Jump backward 5 seconds |
| **Q / Esc** | Quit picker and return here |
""")
        col1, col2 = st.columns([2, 1])
        with col1:
            if st.button("Done — Load Captured Frames", type="primary"):
                if proc and proc.poll() is None:
                    proc.wait(timeout=10)
                _load_captured_frames()
                st.rerun()
        with col2:
            if st.button("Refresh Status"):
                st.rerun()

    # ── Stage 4: Review and save ─────────────────────────────────────────────
    elif stage == 'frames_ready':
        captured = st.session_state.yt_captured_frames or []

        if not captured:
            st.warning("No frames were captured.")
            if st.button("Re-launch Frame Picker"):
                st.session_state.yt_stage = 'downloaded'
                st.rerun()
            return

        st.markdown(f"**Step 3 of 3 — Review {len(captured)} captured frame(s)**")
        st.caption("Uncheck any frames you do not want to save.")

        col_all, col_none = st.columns([1, 1])
        with col_all:
            if st.button("Select All"):
                for i in range(len(captured)):
                    st.session_state[f'yt_keep_{i}'] = True
                st.rerun()
        with col_none:
            if st.button("Deselect All"):
                for i in range(len(captured)):
                    st.session_state[f'yt_keep_{i}'] = False
                st.rerun()

        COLS = 4
        for row_start in range(0, len(captured), COLS):
            cols = st.columns(COLS)
            for ci in range(COLS):
                idx = row_start + ci
                if idx >= len(captured):
                    break
                frame = captured[idx]
                with cols[ci]:
                    fpath = Path(frame.get('path', ''))
                    if fpath.exists():
                        st.image(str(fpath), use_container_width=True)
                    st.checkbox(
                        f"{frame['timestamp_s']:.1f}s",
                        key=f"yt_keep_{idx}",
                    )

        n_keep = sum(1 for i in range(len(captured))
                     if st.session_state.get(f'yt_keep_{i}', True))

        st.divider()
        if n_keep == 0:
            st.warning("No frames selected.")
        else:
            if st.button(f"Save {n_keep} Frame(s) to Database", type="primary"):
                _save_yt_frames(captured, metadata)


# ---------------------------------------------------------------------------


def _show_pagination(max_page, position):
    """Show pagination controls. Position is used to create unique button keys."""
    col_first, col_prev, col_info, col_next, col_last, col_goto = st.columns([0.7, 0.9, 1.5, 0.7, 0.7, 1.5])
    with col_first:
        if st.session_state.page > 0:
            if st.button("First", key=f"first_{position}"):
                st.session_state.page = 0
                st.rerun()
    with col_prev:
        if st.session_state.page > 0:
            if st.button("Previous", key=f"prev_{position}"):
                st.session_state.page -= 1
                st.rerun()
    with col_info:
        st.write(f"Page {st.session_state.page + 1} of {max_page + 1}")
    with col_next:
        if st.session_state.page < max_page:
            if st.button("Next", key=f"next_{position}"):
                st.session_state.page += 1
                st.rerun()
    with col_last:
        if st.session_state.page < max_page:
            if st.button("Last", key=f"last_{position}"):
                st.session_state.page = max_page
                st.rerun()
    with col_goto:
        def _goto_page(key):
            st.session_state.page = st.session_state[key] - 1

        gkey = f"goto_{position}"
        # Sync widget state with current page to avoid stale values
        st.session_state[gkey] = st.session_state.page + 1
        st.number_input("Go to page", min_value=1, max_value=max_page + 1,
                        step=1, key=gkey, label_visibility="collapsed",
                        on_change=_goto_page, args=(gkey,))


def show_browse_view():
    """Show the paginated table of meteorites."""
    if st.button("New Meteorite", type="primary"):
        st.session_state.view = 'add_new'
        st.rerun()

    try:
        total = db.get_meteorite_count(filters if filters else None)
    except Exception as e:
        st.error(f"Database error: {e}")
        return

    st.write(f"**{total}** meteorites found")

    if total == 0:
        return

    # Pagination
    max_page = max(0, (total - 1) // PAGE_SIZE)
    st.session_state.page = min(st.session_state.page, max_page)

    offset = st.session_state.page * PAGE_SIZE

    try:
        rows = db.get_all_meteorites(
            filters=filters if filters else None,
            limit=PAGE_SIZE,
            offset=offset
        )
    except Exception as e:
        st.error(f"Database error: {e}")
        return

    # Pagination controls (top)
    _show_pagination(max_page, "top")

    # Column headers
    col_act, col_id, col_thumb, col_nr, col_name, col_pt, col_pq, col_type, col_class, col_ctx, col_del = st.columns([1, 0.5, 1, 1, 2.5, 1.5, 1.5, 2, 2, 2, 1])
    with col_act:
        st.markdown("**Action**")
    with col_id:
        st.markdown("**ID**")
    with col_thumb:
        st.markdown("**Image**")
    with col_nr:
        st.markdown("**Needs Review**")
    with col_name:
        st.markdown("**Name**")
    with col_pt:
        st.markdown('<div style="text-align:center"><strong>In Situ</strong></div>', unsafe_allow_html=True)
    with col_pq:
        st.markdown("**Photo Quality**")
    with col_type:
        st.markdown("**Primary Type**")
    with col_class:
        st.markdown("**Classification**")
    with col_ctx:
        st.markdown("**Context**")
    with col_del:
        st.markdown("**Delete**")

    # Display table
    for row in rows:
        col_act, col_id, col_thumb, col_nr, col_name, col_pt, col_pq, col_type, col_class, col_ctx, col_del = st.columns([1, 0.5, 1, 1, 2.5, 1.5, 1.5, 2, 2, 2, 1])
        with col_act:
            if st.button("View", key=f"view_{row['image_id']}"):
                st.session_state.selected_id = row['image_id']
                st.session_state.view = 'detail'
                st.session_state.confirm_delete = False
                st.session_state.list_confirm_delete = None
                st.rerun()
        with col_id:
            st.write(row['image_id'])
        with col_thumb:
            stored_filename = row.get('stored_filename', '')
            image_path = IMAGES_DIR / stored_filename if stored_filename else None
            if image_path and image_path.exists():
                st.image(str(image_path), width=60)
        with col_nr:
            st.markdown(
                f'<div style="text-align:center">{"&#9745;" if row.get("needs_review") else "&#9744;"}</div>',
                unsafe_allow_html=True
            )
        with col_name:
            st.write(row.get('meteorite_name', '—'))
        with col_pt:
            st.markdown(
                f'<div style="text-align:center">{"&#9745;" if row.get("in_situ") else "&#9744;"}</div>',
                unsafe_allow_html=True
            )
        with col_pq:
            st.write(row.get('photo_quality', '—') or '—')
        with col_type:
            st.write(row.get('primary_type', '—') or '—')
        with col_class:
            st.write(row.get('detailed_classification', '—') or '—')
        with col_ctx:
            st.write(row.get('image_context', '—') or '—')
        with col_del:
            rid = row['image_id']
            if st.session_state.list_confirm_delete == rid:
                if st.button("Confirm", key=f"confirm_del_{rid}"):
                    try:
                        stored_fn = db.delete_meteorite(rid)
                        if stored_fn:
                            img_p = IMAGES_DIR / stored_fn
                            if img_p.exists():
                                img_p.unlink()
                            json_p = METADATA_DIR / (Path(stored_fn).stem + ".json")
                            if json_p.exists():
                                json_p.unlink()
                        st.session_state.list_confirm_delete = None
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")
            else:
                with st.container():
                    st.markdown('<div class="row-delete">', unsafe_allow_html=True)
                    if st.button("Delete", key=f"del_{rid}"):
                        st.session_state.list_confirm_delete = rid
                        st.rerun()
                    st.markdown('</div>', unsafe_allow_html=True)

    # Pagination controls (bottom)
    _show_pagination(max_page, "bottom")

    if st.button("New Meteorite", type="primary", key="new_meteorite_bottom"):
        st.session_state.view = 'add_new'
        st.rerun()


def show_detail_view(image_id):
    """Show detail/edit view for a single meteorite."""
    if st.button("Back to list"):
        st.session_state.selected_id = None
        st.session_state.view = 'browse'
        st.session_state.confirm_delete = False
        st.rerun()

    try:
        record = db.get_meteorite_by_id(image_id)
    except Exception as e:
        st.error(f"Database error: {e}")
        return

    if not record:
        st.error(f"Meteorite with ID {image_id} not found.")
        return

    st.subheader(f"{record.get('meteorite_name', 'Unknown')} (ID: {image_id})")

    # Show image
    img_col, info_col = st.columns([1, 1])

    with img_col:
        stored_filename = record.get('stored_filename', '')
        image_path = IMAGES_DIR / stored_filename if stored_filename else None
        if image_path and image_path.exists():
            st.image(str(image_path), width="stretch")
        else:
            st.warning("Image file not found on disk")

        st.caption(f"File: {stored_filename}")
        if record.get('source_url'):
            st.caption(f"Source: {record['source_url']}")

    # Edit form
    with info_col:
        with st.form("edit_form"):
            submitted = st.form_submit_button("Save Changes")

            st.markdown("#### Image Context")
            in_situ = st.checkbox("In Situ", value=bool(record.get('in_situ')))
            from_drone = st.checkbox("From Drone", value=bool(record.get('from_drone')))
            sectioned = st.checkbox("Sectioned", value=bool(record.get('sectioned')))
            needs_review = st.checkbox("Needs review", value=bool(record.get('needs_review')))
            parent_url = st.text_input("Parent URL", value=record.get('parent_url', '') or '')
            photo_quality_options = ["", "High", "Medium", "Low"]
            photo_quality = st.selectbox("Photo quality", photo_quality_options,
                                         index=photo_quality_options.index(record.get('photo_quality', '') or ''))
            image_context = st.text_input("Image context", value=record.get('image_context', '') or '')
            viewing_angle = st.text_input("Viewing angle", value=record.get('viewing_angle', '') or '')
            background_type = st.text_input("Background type", value=record.get('background_type', '') or '')
            lighting_type = st.text_input("Lighting type", value=record.get('lighting_type', '') or '')

            notes = st.text_area("Notes", value=record.get('notes', '') or '')

            st.markdown("#### Classification")
            meteorite_name = st.text_input("Name", value=record.get('meteorite_name', '') or '')
            primary_type = st.text_input("Primary type", value=record.get('primary_type', '') or '')
            secondary_type = st.text_input("Secondary type", value=record.get('secondary_type', '') or '')
            detailed_classification = st.text_input("Detailed classification", value=record.get('detailed_classification', '') or '')
            weathering_grade = st.text_input("Weathering grade", value=record.get('weathering_grade', '') or '')

            st.markdown("#### Physical Characteristics")
            mass_grams = st.text_input("Mass (grams)", value=str(record.get('mass_grams', '') or ''))
            fusion_crust_present = st.checkbox("Fusion crust present", value=bool(record.get('fusion_crust_present')))
            regmaglypts_present = st.checkbox("Regmaglypts present", value=bool(record.get('regmaglypts_present')))
            visible_metal = st.checkbox("Visible metal", value=bool(record.get('visible_metal')))

            st.markdown("#### Discovery Info")
            fall_or_find = st.selectbox("Fall or find", ["", "fall", "find"],
                                        index=["", "fall", "find"].index(record.get('fall_or_find', '') or ''))
            discovery_location = st.text_input("Discovery location", value=record.get('discovery_location', '') or '')
            discovery_latitude = st.text_input("Latitude", value=str(record.get('discovery_latitude', '') or ''))
            discovery_longitude = st.text_input("Longitude", value=str(record.get('discovery_longitude', '') or ''))
            terrain_type = st.text_input("Terrain type", value=record.get('terrain_type', '') or '')

            if submitted:
                def to_decimal(val):
                    if val.strip() == '':
                        return None
                    try:
                        return float(val)
                    except ValueError:
                        return None

                update_data = {
                    'meteorite_name': meteorite_name or None,
                    'primary_type': primary_type or None,
                    'secondary_type': secondary_type or None,
                    'detailed_classification': detailed_classification or None,
                    'weathering_grade': weathering_grade or None,
                    'mass_grams': to_decimal(mass_grams),
                    'fusion_crust_present': fusion_crust_present,
                    'regmaglypts_present': regmaglypts_present,
                    'visible_metal': visible_metal,
                    'fall_or_find': fall_or_find or None,
                    'discovery_location': discovery_location or None,
                    'discovery_latitude': to_decimal(discovery_latitude),
                    'discovery_longitude': to_decimal(discovery_longitude),
                    'terrain_type': terrain_type or None,
                    'in_situ': in_situ,
                    'from_drone': from_drone,
                    'sectioned': sectioned,
                    'photo_quality': photo_quality or None,
                    'image_context': image_context or None,
                    'viewing_angle': viewing_angle or None,
                    'background_type': background_type or None,
                    'lighting_type': lighting_type or None,
                    'needs_review': needs_review,
                    'parent_url': parent_url or None,
                    'notes': notes or None,
                }

                try:
                    db.update_meteorite(image_id, update_data)
                    st.success("Changes saved!")
                except Exception as e:
                    st.error(f"Error saving: {e}")

    # Delete section
    st.divider()
    st.markdown("#### Delete Meteorite")

    if not st.session_state.confirm_delete:
        if st.button("Delete this meteorite", type="secondary"):
            st.session_state.confirm_delete = True
            st.rerun()
    else:
        st.warning("Are you sure? This will delete the database record, the image file, and the metadata JSON.")
        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button("Yes, delete it", type="primary"):
                try:
                    stored_filename = db.delete_meteorite(image_id)
                    if stored_filename:
                        # Delete image file
                        img_path = IMAGES_DIR / stored_filename
                        if img_path.exists():
                            img_path.unlink()
                        # Delete metadata JSON
                        json_path = METADATA_DIR / (Path(stored_filename).stem + ".json")
                        if json_path.exists():
                            json_path.unlink()
                    st.session_state.selected_id = None
                    st.session_state.confirm_delete = False
                    st.success("Deleted!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error deleting: {e}")
        with col_no:
            if st.button("Cancel"):
                st.session_state.confirm_delete = False
                st.rerun()

    # Bottom back button
    st.divider()
    if st.button("Back to list", key="back_bottom"):
        st.session_state.selected_id = None
        st.session_state.view = 'browse'
        st.session_state.confirm_delete = False
        st.rerun()


def _fetch_and_store_image(url):
    """Download an image from a URL, validate it, and save to disk. Returns (filename, image_info) or raises."""
    response = requests.get(url, headers=SCRAPE_CONFIG.get('headers', {}),
                            timeout=SCRAPE_CONFIG['request_timeout'])
    response.raise_for_status()
    image_data = response.content

    image_info = validate_image(image_data)
    if not image_info:
        raise ValueError("Image validation failed — too small, too large, or not a valid image format.")

    extension = image_info['format']
    if extension == 'jpeg':
        extension = 'jpg'

    filename = generate_filename(url, None, extension)
    filepath = IMAGES_DIR / filename
    with open(filepath, 'wb') as f:
        f.write(image_data)

    return filename, image_info


def show_add_view():
    """Show the add-new-meteorite page."""
    if st.button("Back to list"):
        st.session_state.view = 'browse'
        st.rerun()

    st.subheader("Add New Meteorite")

    # Warn about missing YouTube dependencies before the form so it's always visible
    if not YT_DLP_AVAILABLE or not CV2_AVAILABLE:
        missing = []
        if not YT_DLP_AVAILABLE:
            missing.append("`yt-dlp`")
        if not CV2_AVAILABLE:
            missing.append("`opencv-python`")
        st.warning(
            f"YouTube URL support requires {' and '.join(missing)}. "
            f"Install with: `pip install yt-dlp opencv-python`"
        )

    with st.form("add_form"):
        submitted = st.form_submit_button("Save Meteorite")

        st.markdown("#### Image URL")
        image_url = st.text_input("Image URL", placeholder="https://example.com/meteorite.jpg  or  https://youtube.com/watch?v=...")

        st.markdown("#### Image Context")
        in_situ = st.checkbox("In Situ", key="add_in_situ")
        from_drone = st.checkbox("From Drone", key="add_from_drone")
        sectioned = st.checkbox("Sectioned", key="add_sectioned")
        needs_review = st.checkbox("Needs review", value=False)
        parent_url = st.text_input("Parent URL")
        photo_quality_options = ["", "High", "Medium", "Low"]
        photo_quality = st.selectbox("Photo quality", photo_quality_options)
        image_context = st.text_input("Image context")
        viewing_angle = st.text_input("Viewing angle")
        background_type = st.text_input("Background type")
        lighting_type = st.text_input("Lighting type")
        notes = st.text_area("Notes")

        st.markdown("#### Classification")
        existing_names = db.get_distinct_values('meteorite_name')
        name_options = [""] + existing_names
        selected_name = st.selectbox("Name (select existing)", name_options, index=0)
        new_name = st.text_input("Or enter new name")
        meteorite_name = new_name if new_name else selected_name
        primary_type = st.text_input("Primary type")
        secondary_type = st.text_input("Secondary type")
        detailed_classification = st.text_input("Detailed classification")
        weathering_grade = st.text_input("Weathering grade")

        st.markdown("#### Physical Characteristics")
        mass_grams = st.text_input("Mass (grams)")
        fusion_crust_present = st.checkbox("Fusion crust present")
        regmaglypts_present = st.checkbox("Regmaglypts present")
        visible_metal = st.checkbox("Visible metal")

        st.markdown("#### Discovery Info")
        fall_or_find = st.selectbox("Fall or find", ["", "fall", "find"])
        existing_locations = db.get_distinct_values('discovery_location')
        location_options = [""] + existing_locations
        selected_location = st.selectbox("Discovery location (select existing)", location_options, index=0)
        new_location = st.text_input("Or enter new discovery location")
        discovery_location = new_location if new_location else selected_location
        discovery_latitude = st.text_input("Latitude")
        discovery_longitude = st.text_input("Longitude")
        terrain_type = st.text_input("Terrain type")

        if submitted:
            if not image_url:
                st.error("Please enter an image URL.")

            # ── YouTube URL → hand off to the frame picker ───────────────────
            elif is_youtube_url(image_url):
                if not YT_DLP_AVAILABLE:
                    st.error("yt-dlp not installed. Run: `pip install yt-dlp`")
                elif not CV2_AVAILABLE:
                    st.error("opencv-python not installed. Run: `pip install opencv-python`")
                else:
                    def _to_dec(val):
                        try:
                            return float(val) if val and str(val).strip() else None
                        except ValueError:
                            return None

                    st.session_state.yt_url = image_url
                    st.session_state.yt_metadata = {
                        'meteorite_name':          new_name if new_name else selected_name,
                        'primary_type':            primary_type,
                        'secondary_type':          secondary_type,
                        'detailed_classification': detailed_classification,
                        'weathering_grade':        weathering_grade,
                        'mass_grams':              _to_dec(mass_grams),
                        'fall_or_find':            fall_or_find or None,
                        'discovery_location':      new_location if new_location else selected_location,
                        'discovery_latitude':      _to_dec(discovery_latitude),
                        'discovery_longitude':     _to_dec(discovery_longitude),
                        'terrain_type':            terrain_type,
                        'in_situ':                 in_situ,
                        'from_drone':              from_drone,
                        'sectioned':               sectioned,
                        'fusion_crust_present':    fusion_crust_present,
                        'regmaglypts_present':     regmaglypts_present,
                        'visible_metal':           visible_metal,
                        'photo_quality':           photo_quality or None,
                        'image_context':           image_context,
                        'viewing_angle':           viewing_angle,
                        'background_type':         background_type,
                        'lighting_type':           lighting_type,
                        'needs_review':            needs_review,
                        'parent_url':              parent_url,
                        'notes':                   notes,
                        'weathering_grade':        weathering_grade,
                    }
                    st.session_state.yt_stage = None
                    st.session_state.yt_video_path = None
                    st.session_state.yt_video_info = None
                    st.session_state.yt_process = None
                    st.session_state.yt_captured_frames = None
                    st.session_state.view = 'youtube_picker'
                    st.rerun()

            elif db.url_exists(image_url):
                st.error("This image URL is already in the database.")
            else:
                def to_decimal(val):
                    if not val or val.strip() == '':
                        return None
                    try:
                        return float(val)
                    except ValueError:
                        return None

                try:
                    with st.spinner("Downloading image..."):
                        filename, image_info = _fetch_and_store_image(image_url)

                    # Update filename with meteorite name if provided
                    if meteorite_name:
                        new_filename = generate_filename(image_url, meteorite_name, image_info['format'] if image_info['format'] != 'jpeg' else 'jpg')
                        new_path = IMAGES_DIR / new_filename
                        old_path = IMAGES_DIR / filename
                        if old_path.exists() and not new_path.exists():
                            old_path.rename(new_path)
                            filename = new_filename

                    db_data = {
                        'meteorite_name': meteorite_name or None,
                        'original_filename': image_url.split('/')[-1],
                        'stored_filename': filename,
                        'source_url': image_url,
                        'page_url': None,
                        'photo_page_url': None,
                        'file_format': image_info['format'] if image_info['format'] != 'jpeg' else 'jpg',
                        'file_size_bytes': image_info['size_bytes'],
                        'width_px': image_info['width'],
                        'height_px': image_info['height'],
                        'primary_type': primary_type or None,
                        'secondary_type': secondary_type or None,
                        'detailed_classification': detailed_classification or None,
                        'mass_grams': to_decimal(mass_grams),
                        'fall_or_find': fall_or_find or None,
                        'discovery_date': None,
                        'discovery_location': discovery_location or None,
                        'discovery_latitude': to_decimal(discovery_latitude),
                        'discovery_longitude': to_decimal(discovery_longitude),
                        'terrain_type': terrain_type or None,
                        'image_context': image_context or None,
                        'viewing_angle': viewing_angle or None,
                        'background_type': background_type or None,
                        'lighting_type': lighting_type or None,
                        'license': None,
                        'photographer': None,
                        'needs_review': needs_review,
                        'notes': notes or None,
                    }

                    image_id = db.insert_meteorite(db_data)

                    # Save metadata JSON sidecar
                    save_metadata_json(image_id, {
                        'meteorite_name': meteorite_name,
                        'source_url': image_url,
                    }, filename)

                    # Update with extra fields not in insert_meteorite
                    extra_fields = {
                        'in_situ': in_situ,
                        'from_drone': from_drone,
                        'sectioned': sectioned,
                        'fusion_crust_present': fusion_crust_present,
                        'regmaglypts_present': regmaglypts_present,
                        'visible_metal': visible_metal,
                        'parent_url': parent_url or None,
                    }
                    if photo_quality:
                        extra_fields['photo_quality'] = photo_quality
                    if weathering_grade:
                        extra_fields['weathering_grade'] = weathering_grade
                    db.update_meteorite(image_id, extra_fields)
                    ls_push_task({**db_data, 'image_id': image_id})

                    st.success(f"Meteorite added with ID {image_id}!")
                    st.session_state.selected_id = image_id
                    st.session_state.view = 'detail'
                    st.rerun()

                except requests.RequestException as e:
                    st.error(f"Failed to download image: {e}")
                except ValueError as e:
                    st.error(str(e))
                except Exception as e:
                    st.error(f"Error: {e}")


# --- Main routing ---
if st.session_state.view == 'youtube_picker':
    show_youtube_picker_view()
elif st.session_state.view == 'add_new':
    show_add_view()
elif st.session_state.selected_id is not None:
    st.session_state.view = 'detail'
    show_detail_view(st.session_state.selected_id)
else:
    st.session_state.view = 'browse'
    show_browse_view()
