import sys
from sqlalchemy import text
from database import engine

def run():
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE cafes ADD COLUMN image_url VARCHAR(500);"))
            print("Successfully added image_url column.")
        except Exception as e:
            print(f"Error (maybe column exists?): {e}")

if __name__ == "__main__":
    run()
