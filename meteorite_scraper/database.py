import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
import logging
from config import DB_CONFIG

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Handles all database operations"""
    
    def __init__(self):
        self.config = DB_CONFIG
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections"""
        conn = None
        try:
            conn = psycopg2.connect(**self.config)
            yield conn
            conn.commit()
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            if conn:
                conn.close()
    
    def insert_meteorite(self, data):
        """Insert a meteorite record and return the image_id"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            query = """
                INSERT INTO meteorites (
                    meteorite_name, original_filename, stored_filename,
                    source_url, page_url, photo_page_url, file_format, file_size_bytes,
                    width_px, height_px, primary_type, secondary_type,
                    detailed_classification, mass_grams, fall_or_find,
                    discovery_date, discovery_location, discovery_latitude,
                    discovery_longitude, terrain_type, image_context,
                    viewing_angle, background_type, lighting_type,
                    license, photographer, needs_review, notes
                ) VALUES (
                    %(meteorite_name)s, %(original_filename)s, %(stored_filename)s,
                    %(source_url)s, %(page_url)s, %(photo_page_url)s, %(file_format)s, %(file_size_bytes)s,
                    %(width_px)s, %(height_px)s, %(primary_type)s, %(secondary_type)s,
                    %(detailed_classification)s, %(mass_grams)s, %(fall_or_find)s,
                    %(discovery_date)s, %(discovery_location)s, %(discovery_latitude)s,
                    %(discovery_longitude)s, %(terrain_type)s, %(image_context)s,
                    %(viewing_angle)s, %(background_type)s, %(lighting_type)s,
                    %(license)s, %(photographer)s, %(needs_review)s, %(notes)s
                )
                RETURNING image_id
            """

            cursor.execute(query, data)
            image_id = cursor.fetchone()[0]
            logger.info(f"Inserted meteorite record with ID: {image_id}")
            return image_id
    
    def url_exists(self, url):
        """Check if a URL has already been scraped"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM meteorites WHERE source_url = %s",
                (url,)
            )
            return cursor.fetchone()[0] > 0

    def photo_page_url_exists(self, photo_page_url):
        """Check if a photo page URL has already been processed"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM meteorites WHERE photo_page_url = %s",
                (photo_page_url,)
            )
            return cursor.fetchone()[0] > 0

    def update_photo_page_url(self, source_url, photo_page_url):
        """
        Update an existing record to add the photo_page_url.

        Args:
            source_url: The actual image URL (source_url in database)
            photo_page_url: The photo page URL to add

        Returns:
            True if updated, False if record not found
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE meteorites
                SET photo_page_url = %s
                WHERE source_url = %s AND (photo_page_url IS NULL OR photo_page_url = '')
                """,
                (photo_page_url, source_url)
            )
            rows_updated = cursor.rowcount
            if rows_updated > 0:
                logger.info(f"Updated photo_page_url for existing image: {source_url}")
                return True
            return False

    def get_meteorite_by_id(self, image_id):
        """Retrieve a meteorite record by ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                "SELECT * FROM meteorites WHERE image_id = %s",
                (image_id,)
            )
            return cursor.fetchone()
    
    def log_scrape_session(self, source_name, images_found, images_downloaded, errors, status, notes=""):
        """Log a scraping session"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO scrape_logs 
                (source_name, images_found, images_downloaded, errors, status, notes)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (source_name, images_found, images_downloaded, errors, status, notes))
    
    def get_statistics(self):
        """Get database statistics"""
        with self.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            stats = {}
            
            # Total images
            cursor.execute("SELECT COUNT(*) as total FROM meteorites")
            stats['total_images'] = cursor.fetchone()['total']
            
            # By type
            cursor.execute("""
                SELECT primary_type, COUNT(*) as count 
                FROM meteorites 
                WHERE primary_type IS NOT NULL
                GROUP BY primary_type
            """)
            stats['by_type'] = {row['primary_type']: row['count'] for row in cursor.fetchall()}
            
            # By context
            cursor.execute("""
                SELECT image_context, COUNT(*) as count 
                FROM meteorites 
                WHERE image_context IS NOT NULL
                GROUP BY image_context
            """)
            stats['by_context'] = {row['image_context']: row['count'] for row in cursor.fetchall()}
            
            # Needs review
            cursor.execute("SELECT COUNT(*) as count FROM meteorites WHERE needs_review = TRUE")
            stats['needs_review'] = cursor.fetchone()['count']
            
            return stats

    def get_all_meteorites(self, filters=None, limit=50, offset=0):
        """Get paginated list of meteorites with optional filters"""
        with self.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            where_clauses = []
            params = []

            if filters:
                if filters.get('meteorite_name'):
                    where_clauses.append("meteorite_name ILIKE %s")
                    params.append(f"%{filters['meteorite_name']}%")
                if filters.get('in_situ'):
                    where_clauses.append("in_situ = %s")
                    params.append(True)
                if filters.get('primary_type'):
                    where_clauses.append("primary_type = %s")
                    params.append(filters['primary_type'])
                if filters.get('image_context'):
                    where_clauses.append("image_context = %s")
                    params.append(filters['image_context'])
                if filters.get('needs_review') is not None:
                    where_clauses.append("needs_review = %s")
                    params.append(filters['needs_review'])

            where_sql = ""
            if where_clauses:
                where_sql = "WHERE " + " AND ".join(where_clauses)

            query = f"""
                SELECT * FROM meteorites
                {where_sql}
                ORDER BY image_id ASC
                LIMIT %s OFFSET %s
            """
            params.extend([limit, offset])

            cursor.execute(query, params)
            return cursor.fetchall()

    def get_meteorite_count(self, filters=None):
        """Get total count of meteorites matching filters"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            where_clauses = []
            params = []

            if filters:
                if filters.get('meteorite_name'):
                    where_clauses.append("meteorite_name ILIKE %s")
                    params.append(f"%{filters['meteorite_name']}%")
                if filters.get('in_situ'):
                    where_clauses.append("in_situ = %s")
                    params.append(True)
                if filters.get('primary_type'):
                    where_clauses.append("primary_type = %s")
                    params.append(filters['primary_type'])
                if filters.get('image_context'):
                    where_clauses.append("image_context = %s")
                    params.append(filters['image_context'])
                if filters.get('needs_review') is not None:
                    where_clauses.append("needs_review = %s")
                    params.append(filters['needs_review'])

            where_sql = ""
            if where_clauses:
                where_sql = "WHERE " + " AND ".join(where_clauses)

            cursor.execute(f"SELECT COUNT(*) FROM meteorites {where_sql}", params)
            return cursor.fetchone()[0]

    def get_distinct_values(self, column):
        """Get distinct non-null values for a column (for filter dropdowns)"""
        allowed_columns = {'primary_type', 'secondary_type', 'image_context',
                           'fall_or_find', 'terrain_type',
                           'photo_type', 'discovery_location', 'meteorite_name'}
        if column not in allowed_columns:
            raise ValueError(f"Column '{column}' not allowed for distinct query")

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT DISTINCT {column} FROM meteorites WHERE {column} IS NOT NULL ORDER BY {column}"
            )
            return [row[0] for row in cursor.fetchall()]

    def update_meteorite(self, image_id, data):
        """Update editable fields for a meteorite record"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            set_clauses = []
            params = []
            for key, value in data.items():
                set_clauses.append(f"{key} = %s")
                params.append(value)

            params.append(image_id)
            query = f"""
                UPDATE meteorites
                SET {', '.join(set_clauses)}
                WHERE image_id = %s
            """
            cursor.execute(query, params)
            logger.info(f"Updated meteorite record {image_id}")
            return cursor.rowcount > 0

    def delete_meteorite(self, image_id):
        """Delete a meteorite record and return the stored_filename for file cleanup"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT stored_filename FROM meteorites WHERE image_id = %s",
                (image_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None

            stored_filename = row[0]
            cursor.execute("DELETE FROM meteorites WHERE image_id = %s", (image_id,))
            logger.info(f"Deleted meteorite record {image_id} ({stored_filename})")
            return stored_filename
