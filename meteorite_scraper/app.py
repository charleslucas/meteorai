import streamlit as st
import sys
import os
import requests
import io
from pathlib import Path

# Add the meteorite_scraper directory to path so imports work
sys.path.insert(0, str(Path(__file__).parent))

from database import DatabaseManager
from config import IMAGES_DIR, METADATA_DIR, SCRAPE_CONFIG
from utils import generate_filename, validate_image, save_metadata_json

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

PAGE_SIZE = 25


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
        st.markdown("**In Situ**")
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
            sectioned = st.checkbox("Sectioned", value=bool(record.get('sectioned')))
            photo_quality_options = ["", "High", "Medium", "Low"]
            photo_quality = st.selectbox("Photo quality", photo_quality_options,
                                         index=photo_quality_options.index(record.get('photo_quality', '') or ''))
            image_context = st.text_input("Image context", value=record.get('image_context', '') or '')
            viewing_angle = st.text_input("Viewing angle", value=record.get('viewing_angle', '') or '')
            background_type = st.text_input("Background type", value=record.get('background_type', '') or '')
            lighting_type = st.text_input("Lighting type", value=record.get('lighting_type', '') or '')

            st.markdown("#### Metadata")
            data_confidence = st.selectbox("Data confidence", ["", "low", "medium", "high"],
                                           index=["", "low", "medium", "high"].index(record.get('data_confidence', '') or ''))
            needs_review = st.checkbox("Needs review", value=bool(record.get('needs_review')))
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
                    'sectioned': sectioned,
                    'photo_quality': photo_quality or None,
                    'image_context': image_context or None,
                    'viewing_angle': viewing_angle or None,
                    'background_type': background_type or None,
                    'lighting_type': lighting_type or None,
                    'data_confidence': data_confidence or None,
                    'needs_review': needs_review,
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

    with st.form("add_form"):
        submitted = st.form_submit_button("Save Meteorite")

        st.markdown("#### Image URL")
        image_url = st.text_input("Image URL", placeholder="https://example.com/meteorite.jpg")

        st.markdown("#### Image Context")
        in_situ = st.checkbox("In Situ", key="add_in_situ")
        sectioned = st.checkbox("Sectioned", key="add_sectioned")
        photo_quality_options = ["", "High", "Medium", "Low"]
        photo_quality = st.selectbox("Photo quality", photo_quality_options)
        image_context = st.text_input("Image context")
        viewing_angle = st.text_input("Viewing angle")
        background_type = st.text_input("Background type")
        lighting_type = st.text_input("Lighting type")

        st.markdown("#### Metadata")
        data_confidence = st.selectbox("Data confidence", ["", "low", "medium", "high"])
        needs_review = st.checkbox("Needs review", value=True)
        notes = st.text_area("Notes")

        st.markdown("#### Classification")
        meteorite_name = st.text_input("Name")
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
        discovery_location = st.text_input("Discovery location")
        discovery_latitude = st.text_input("Latitude")
        discovery_longitude = st.text_input("Longitude")
        terrain_type = st.text_input("Terrain type")

        if submitted:
            if not image_url:
                st.error("Please enter an image URL.")
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
                        'data_confidence': data_confidence or None,
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
                        'sectioned': sectioned,
                    }
                    if photo_quality:
                        extra_fields['photo_quality'] = photo_quality
                    if weathering_grade:
                        extra_fields['weathering_grade'] = weathering_grade
                    db.update_meteorite(image_id, extra_fields)

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
if st.session_state.view == 'add_new':
    show_add_view()
elif st.session_state.selected_id is not None:
    st.session_state.view = 'detail'
    show_detail_view(st.session_state.selected_id)
else:
    st.session_state.view = 'browse'
    show_browse_view()
