from db_config import get_connection
from datetime import datetime

def test_insert():
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Insert a test record
        cursor.execute("""
            INSERT INTO meteorites 
            (meteorite_name, stored_filename, source_url, primary_type, 
             file_format, file_size_bytes, needs_review)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING image_id
        """, (
            'Test Meteorite',
            'test_001.jpg',
            'https://example.com/test.jpg',
            'stony',
            'jpg',
            102400,
            True
        ))
        
        image_id = cursor.fetchone()[0]
        conn.commit()
        
        print(f"Successfully inserted test record with ID: {image_id}")
        
        # Retrieve it
        cursor.execute("SELECT * FROM meteorites WHERE image_id = %s", (image_id,))
        record = cursor.fetchone()
        print(f"\nRetrieved record: {record}")
        
        # Clean up test data
        cursor.execute("DELETE FROM meteorites WHERE image_id = %s", (image_id,))
        conn.commit()
        print("\nTest record deleted successfully!")
        
    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    test_insert()