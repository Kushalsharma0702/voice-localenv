#!/usr/bin/env python3
"""
Database migration script to add call_status fields to existing customers table
"""

import os
import sys
from sqlalchemy import text
from dotenv import load_dotenv

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Load environment variables
load_dotenv()

from database.schemas import db_manager

def migrate_database():
    """Add new columns to the customers table"""
    session = db_manager.get_session()
    try:
        print("🔄 Starting database migration...")
        
        # Add call_status column
        try:
            session.execute(text("""
                ALTER TABLE customers 
                ADD COLUMN call_status VARCHAR(50) DEFAULT 'ready'
            """))
            print("✅ Added call_status column")
        except Exception as e:
            if "already exists" in str(e) or "duplicate column" in str(e).lower():
                print("⚠️ call_status column already exists")
            else:
                print(f"❌ Error adding call_status column: {e}")
        
        # Add last_call_attempt column
        try:
            session.execute(text("""
                ALTER TABLE customers 
                ADD COLUMN last_call_attempt TIMESTAMP
            """))
            print("✅ Added last_call_attempt column")
        except Exception as e:
            if "already exists" in str(e) or "duplicate column" in str(e).lower():
                print("⚠️ last_call_attempt column already exists")
            else:
                print(f"❌ Error adding last_call_attempt column: {e}")
        
        # Add call_attempts column
        try:
            session.execute(text("""
                ALTER TABLE customers 
                ADD COLUMN call_attempts INTEGER DEFAULT 0
            """))
            print("✅ Added call_attempts column")
        except Exception as e:
            if "already exists" in str(e) or "duplicate column" in str(e).lower():
                print("⚠️ call_attempts column already exists")
            else:
                print(f"❌ Error adding call_attempts column: {e}")
        
        # Update existing customers to have 'ready' status if NULL
        try:
            result = session.execute(text("""
                UPDATE customers 
                SET call_status = 'ready' 
                WHERE call_status IS NULL
            """))
            print(f"✅ Updated {result.rowcount} customers with default 'ready' status")
        except Exception as e:
            print(f"❌ Error updating existing customers: {e}")
        
        session.commit()
        print("🎉 Database migration completed successfully!")
        
    except Exception as e:
        session.rollback()
        print(f"❌ Migration failed: {e}")
        raise
    finally:
        session.close()

if __name__ == "__main__":
    try:
        migrate_database()
    except Exception as e:
        print(f"💥 Critical error during migration: {e}")
        sys.exit(1)
