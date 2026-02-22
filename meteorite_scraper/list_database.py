#!/usr/bin/env python3
"""
List all meteorites in the database
"""

import sys
from pathlib import Path

# Add parent directory to path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent))

from database import DatabaseManager
import logging

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def list_meteorites():
    """List all meteorites in the database"""
    db = DatabaseManager()

    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()

            # Get total count
            cursor.execute("SELECT COUNT(*) FROM meteorites")
            total_count = cursor.fetchone()[0]

            print("=" * 100)
            print(f"METEORITE DATABASE - {total_count} Images Total")
            print("=" * 100)
            print()

            # Get all meteorites ordered by name
            cursor.execute("""
                SELECT
                    image_id,
                    meteorite_name,
                    primary_type,
                    detailed_classification,
                    stored_filename,
                    file_format,
                    width_px,
                    height_px,
                    file_size_bytes,
                    photographer,
                    image_context,
                    created_at
                FROM meteorites
                ORDER BY meteorite_name, image_id
            """)

            current_meteorite = None
            meteorite_count = 0

            for row in cursor.fetchall():
                (image_id, name, ptype, classification, filename, fmt,
                 width, height, size_bytes, photographer, context, created_at) = row

                # Print meteorite header when we encounter a new meteorite
                if name != current_meteorite:
                    if current_meteorite is not None:
                        print()  # Blank line between meteorites

                    meteorite_count += 1
                    current_meteorite = name

                    print(f"\n{meteorite_count}. {name}")
                    if classification:
                        print(f"   Classification: {classification}")
                    elif ptype:
                        print(f"   Type: {ptype}")
                    print(f"   Images:")

                # Print image details (indented)
                size_kb = size_bytes / 1024 if size_bytes else 0
                print(f"      #{image_id:5d} - {filename}")
                print(f"              {width}x{height} {fmt.upper()}, {size_kb:.1f} KB")
                if photographer:
                    print(f"              Photographer: {photographer}")
                if context:
                    print(f"              Context: {context}")
                if created_at:
                    print(f"              Added: {created_at}")

            print()
            print("=" * 100)
            print(f"Total: {meteorite_count} meteorites, {total_count} images")
            print("=" * 100)

    except Exception as e:
        logger.error(f"Error listing meteorites: {e}")
        raise

if __name__ == "__main__":
    list_meteorites()
