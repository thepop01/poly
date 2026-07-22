import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()

try:
    print("Altering wallet_tags...")
    cur.execute("""
        ALTER TABLE wallet_tags
          ADD COLUMN IF NOT EXISTS subcategory_pnl NUMERIC DEFAULT 0,
          ADD COLUMN IF NOT EXISTS subcategory_roi NUMERIC DEFAULT 0,
          ADD COLUMN IF NOT EXISTS subcategory_win_rate NUMERIC DEFAULT 0,
          ADD COLUMN IF NOT EXISTS subcategory_resolved_count INTEGER DEFAULT 0,
          ADD COLUMN IF NOT EXISTS subcategory_volume NUMERIC DEFAULT 0;
    """)

    print("Creating curated_category_tags...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS curated_category_tags (
          address VARCHAR NOT NULL,
          category VARCHAR NOT NULL,
          subcategory VARCHAR,
          tag_type VARCHAR NOT NULL, -- 'category' or 'subcategory'
          category_pnl NUMERIC DEFAULT 0,
          category_roi NUMERIC DEFAULT 0,
          category_win_rate NUMERIC DEFAULT 0,
          category_volume NUMERIC DEFAULT 0,
          resolved_count INTEGER DEFAULT 0,
          computed_at TIMESTAMPTZ DEFAULT NOW(),
          PRIMARY KEY (address, category, subcategory)
        );
    """)
    conn.commit()
    print("Success!")
except Exception as e:
    conn.rollback()
    print("Error:", e)
finally:
    conn.close()
