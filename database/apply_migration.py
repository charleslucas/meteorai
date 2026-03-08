#!/usr/bin/env python3
"""
Apply database migration to add photo_page_url column
"""

import psycopg2
import os
from pathlib import Path

# Get database password from environment
DB_PASSWORD = os.environ.get('DB_PASSWORD')
if not DB_PASSWORD:
    print("ERROR: DB_PASSWORD environment variable not set")
    exit(1)

DB_CONFIG = {
    'dbname': 'meteorite_images',
    'user': 'postgres',
    'password': DB_PASSWORD,
    'host': 'localhost',
    'port': 5432
}

def apply_migration():
    """Apply the add_photo_page_url migration"""
    migration_file = Path(__file__).parent / 'migrations' / 'add_photo_page_url.sql'

    print(f"Reading migration from: {migration_file}")
    with open(migration_file, 'r') as f:
        migration_sql = f.read()

    print("Connecting to database...")
    conn = psycopg2.connect(**DB_CONFIG)

    try:
        cursor = conn.cursor()

        print("Applying migration...")
        cursor.execute(migration_sql)

        conn.commit()
        print("✓ Migration applied successfully!")

        # Verify the column was added
        cursor.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'meteorites'
            AND column_name = 'photo_page_url'
        """)

        result = cursor.fetchone()
        if result:
            print(f"✓ Verified: Column '{result[0]}' added with type '{result[1]}'")
        else:
            print("⚠ Warning: Could not verify column was added")

    except Exception as e:
        conn.rollback()
        print(f"✗ Error applying migration: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    apply_migration()
