import psycopg2
from psycopg2 import Error

def test_connection():
    try:
        # Connect to the database
        connection = psycopg2.connect(
            host="localhost",
            database="meteorite_images",
            user="meteorite_user",
            password="your_secure_password_here",
            port="5432"
        )
        
        # Create a cursor
        cursor = connection.cursor()
        
        # Print PostgreSQL version
        cursor.execute("SELECT version();")
        record = cursor.fetchone()
        print("Connected to PostgreSQL!")
        print("PostgreSQL version:", record[0])
        
        # Test the meteorites table
        cursor.execute("SELECT COUNT(*) FROM meteorites;")
        count = cursor.fetchone()[0]
        print(f"Current number of records in meteorites table: {count}")
        
        cursor.close()
        connection.close()
        print("\nConnection closed successfully!")
        
    except Error as e:
        print(f"Error connecting to PostgreSQL: {e}")

if __name__ == "__main__":
    test_connection()
