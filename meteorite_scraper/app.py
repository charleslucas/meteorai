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

selected_type = st.sidebar.selectbox("Primary type", primary_types)
selected_context = st.sidebar.selectbox("Image context", image_contexts)
filter_needs_review = st.sidebar.checkbox("Needs review only")

# Build filters dict
filters = {}
if name_search:
    filters['meteorite_name'] = name_search
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

PAGE_SIZE = 25


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

    # Display table
    for row in rows:
        col1, col2, col3, col4, col5, col6 = st.columns([1, 3, 2, 2, 2, 1])
        with col1:
            st.write(row['image_id'])
        with col2:
            st.write(row.get('meteorite_name', '—'))
        with col3:
            st.write(row.get('primary_type', '—') or '—')
        with col4:
            st.write(row.get('detailed_classification', '—') or '—')
        with col5:
            st.write(row.get('image_context', '—') or '—')
        with col6:
            if st.button("View", key=f"view_{row['image_id']}"):
                st.session_state.selected_id = row['image_id']
                st.session_state.confirm_delete = False
                st.rerun()

    # Pagination controls
    col_prev, col_info, col_next = st.columns([1, 2, 1])
    with col_prev:
        if st.session_state.page > 0:
            if st.button("Previous"):
                st.session_state.page -= 1
                st.rerun()
    with col_info:
        st.write(f"Page {st.session_state.page + 1} of {max_page + 1}")
    with col_next:
        if st.session_state.page < max_page:
            if st.button("Next"):
                st.session_state.page += 1
                st.rerun()


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
            st.image(str(image_path), use_container_width=True)
        else:
            st.warning("Image file not found on disk")

        st.caption(f"File: {stored_filename}")
        if record.get('source_url'):
            st.caption(f"Source: {record['source_url']}")

    # Edit form
    with info_col:
        with st.form("edit_form"):
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

            st.markdown("#### Image Context")
            image_context = st.text_input("Image context", value=record.get('image_context', '') or '')
            viewing_angle = st.text_input("Viewing angle", value=record.get('viewing_angle', '') or '')
            background_type = st.text_input("Background type", value=record.get('background_type', '') or '')
            lighting_type = st.text_input("Lighting type", value=record.get('lighting_type', '') or '')

            st.markdown("#### Metadata")
            data_confidence = st.selectbox("Data confidence", ["", "low", "medium", "high"],
                                           index=["", "low", "medium", "high"].index(record.get('data_confidence', '') or ''))
            needs_review = st.checkbox("Needs review", value=bool(record.get('needs_review')))
            notes = st.text_area("Notes", value=record.get('notes', '') or '')

            submitted = st.form_submit_button("Save Changes")

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


# --- Main routing ---
if st.session_state.selected_id is not None:
    show_detail_view(st.session_state.selected_id)
else:
    # Column headers
    col1, col2, col3, col4, col5, col6 = st.columns([1, 3, 2, 2, 2, 1])
    with col1:
        st.markdown("**ID**")
    with col2:
        st.markdown("**Name**")
    with col3:
        st.markdown("**Type**")
    with col4:
        st.markdown("**Classification**")
    with col5:
        st.markdown("**Context**")
    with col6:
        st.markdown("**Action**")
    show_browse_view()
