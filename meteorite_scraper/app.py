import streamlit as st
import sys
import os
from pathlib import Path

# Add the meteorite_scraper directory to path so imports work
sys.path.insert(0, str(Path(__file__).parent))

from database import DatabaseManager
from config import IMAGES_DIR, METADATA_DIR

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

photo_types = ["All", "Fall", "Staged", "Sectioned"]
selected_photo_type = st.sidebar.selectbox("Photo type", photo_types)
selected_type = st.sidebar.selectbox("Primary type", primary_types)
selected_context = st.sidebar.selectbox("Image context", image_contexts)
filter_needs_review = st.sidebar.checkbox("Needs review only")

# Build filters dict
filters = {}
if name_search:
    filters['meteorite_name'] = name_search
if selected_photo_type != "All":
    filters['photo_type'] = selected_photo_type
if selected_type != "All":
    filters['primary_type'] = selected_type
if selected_context != "All":
    filters['image_context'] = selected_context
if filter_needs_review:
    filters['needs_review'] = True

# --- Session state ---
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
    col_act, col_id, col_thumb, col_name, col_pt, col_pq, col_type, col_class, col_ctx, col_del = st.columns([1, 0.5, 1, 2.5, 1.5, 1.5, 2, 2, 2, 1])
    with col_act:
        st.markdown("**Action**")
    with col_id:
        st.markdown("**ID**")
    with col_thumb:
        st.markdown("**Image**")
    with col_name:
        st.markdown("**Name**")
    with col_pt:
        st.markdown("**Photo Type**")
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
        col_act, col_id, col_thumb, col_name, col_pt, col_pq, col_type, col_class, col_ctx, col_del = st.columns([1, 0.5, 1, 2.5, 1.5, 1.5, 2, 2, 2, 1])
        with col_act:
            if st.button("View", key=f"view_{row['image_id']}"):
                st.session_state.selected_id = row['image_id']
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
        with col_name:
            st.write(row.get('meteorite_name', '—'))
        with col_pt:
            st.write(row.get('photo_type', '—') or '—')
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


def show_detail_view(image_id):
    """Show detail/edit view for a single meteorite."""
    if st.button("Back to list"):
        st.session_state.selected_id = None
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
            photo_type_options = ["", "Fall", "Staged", "Sectioned"]
            photo_type = st.selectbox("Photo type", photo_type_options,
                                      index=photo_type_options.index(record.get('photo_type', '') or ''))
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
                    'photo_type': photo_type or None,
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
        st.session_state.confirm_delete = False
        st.rerun()


# --- Main routing ---
if st.session_state.selected_id is not None:
    show_detail_view(st.session_state.selected_id)
else:
    show_browse_view()
