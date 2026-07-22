import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()

try:
    cur.execute("""
    ALTER TABLE wallet_tags 
    ADD COLUMN IF NOT EXISTS subcategory_pnl DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS subcategory_roi DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS subcategory_win_rate DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS subcategory_resolved_count INTEGER,
    ADD COLUMN IF NOT EXISTS subcategory_volume DOUBLE PRECISION;
    """)
    conn.commit()
    print("Altered wallet_tags")
except Exception as e:
    conn.rollback()
    print("Error altering wallet_tags:", e)

try:
    cur.execute("""
    CREATE TABLE IF NOT EXISTS curated_category_tags (
        address VARCHAR NOT NULL,
        category VARCHAR NOT NULL,
        subcategory VARCHAR NOT NULL,
        tag_type VARCHAR NOT NULL,
        category_pnl DOUBLE PRECISION,
        category_roi DOUBLE PRECISION,
        category_win_rate DOUBLE PRECISION,
        category_volume DOUBLE PRECISION,
        resolved_count INTEGER,
        computed_at TIMESTAMPTZ,
        PRIMARY KEY (address, category, subcategory)
    );
    """)
    conn.commit()
    print("Created curated_category_tags")
except Exception as e:
    conn.rollback()
    print("Error creating curated_category_tags:", e)

conn.close()
