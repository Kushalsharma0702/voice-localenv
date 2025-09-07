#!/usr/bin/env python3
"""
Database Wipe Script for Voice Assistant Application
WARNING: This script will permanently delete ALL data from the database!
Use with extreme caution and only in development/testing environments.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import redis

# Add current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

# Load environment variables
load_dotenv()

# Import database schemas
from database.schemas import Base, DatabaseManager

def confirm_wipe():
    """Ask for user confirmation before wiping data"""
    print("🚨 WARNING: DATABASE WIPE OPERATION 🚨")
    print("=" * 50)
    print("This script will PERMANENTLY DELETE ALL DATA from:")
    print("• PostgreSQL database (all tables):")
    print("  - customers (customer data)")
    print("  - loans (loan information)")
    print("  - file_uploads (CSV upload tracking)")
    print("  - upload_rows (individual CSV rows)")
    print("  - call_sessions (call session tracking)")
    print("  - call_status_updates (call status history)")
    print("  - call_trigger_log (call trigger logging)")
    print("  - customer_events (customer event tracking)")
    print("  - + any other tables discovered dynamically")
    print("• Redis cache (all keys):")
    print("  - WebSocket sessions")
    print("  - Call session data")
    print("  - Customer cache data")
    print("  - Temporary data")
    print("=" * 50)
    print("⚠️  THIS ACTION CANNOT BE UNDONE! ⚠️")
    print()
    
    # Get current environment info
    db_url = os.getenv('DATABASE_URL', 'Not configured')
    redis_url = os.getenv('REDIS_URL', 'localhost:6379')
    
    print(f"Target Database: {db_url}")
    print(f"Target Redis: {redis_url}")
    print()
    
    confirmation = input("Type 'WIPE ALL DATA' to confirm (case sensitive): ")
    
    if confirmation != "WIPE ALL DATA":
        print("❌ Operation cancelled. Data is safe.")
        return False
    
    # Double confirmation
    final_confirm = input("Are you absolutely sure? Type 'YES' to proceed: ")
    if final_confirm.upper() != "YES":
        print("❌ Operation cancelled. Data is safe.")
        return False
    
    return True

def show_current_data_status():
    """Show current database status before wiping"""
    print("\n📊 Current Database Status:")
    print("-" * 40)
    
    try:
        DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://postgres:Intalksai07@dummy-db.cviea4aicss0.eu-north-1.rds.amazonaws.com:5432/postgres')
        engine = create_engine(DATABASE_URL, echo=False)
        Session = sessionmaker(bind=engine)
        session = Session()
        
        # Discover all tables in the database
        result = session.execute(text("""
            SELECT tablename FROM pg_tables 
            WHERE schemaname = 'public' 
            AND tablename NOT LIKE 'pg_%' 
            AND tablename NOT LIKE 'sql_%'
            ORDER BY tablename
        """))
        
        all_tables = [row[0] for row in result.fetchall()]
        
        # Check record counts for each table
        total_records = 0
        for table_name in all_tables:
            try:
                result = session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                count = result.scalar()
                total_records += count
                print(f"   • {table_name}: {count:,} records")
            except Exception as e:
                print(f"   • {table_name}: Error reading ({e})")
        
        print(f"\n   📈 Total Records: {total_records:,}")
        print(f"   📋 Total Tables: {len(all_tables)}")
        session.close()
        
    except Exception as e:
        print(f"   ❌ Could not read database status: {e}")
    
    # Check Redis status
    try:
        redis_url = os.getenv('REDIS_URL')
        if redis_url:
            r = redis.from_url(redis_url, decode_responses=True)
        else:
            redis_host = os.getenv('REDIS_HOST', 'localhost')
            redis_port = int(os.getenv('REDIS_PORT', 6379))
            r = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
        
        r.ping()
        key_count = len(r.keys('*'))
        print(f"   • Redis Keys: {key_count:,}")
        
    except Exception as e:
        print(f"   • Redis: Not accessible ({e})")

def wipe_postgresql_data():
    """Wipe all data from PostgreSQL database"""
    print("\n🗑️  Wiping PostgreSQL Database...")
    print("-" * 40)
    
    try:
        # Initialize database connection
        DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://postgres:IntalksAI07@db-voice-agent.cviea4aicss0.ap-south-1.rds.amazonaws.com:5432/db-voice-agent')
        engine = create_engine(DATABASE_URL, echo=False)
        
        # Create session
        Session = sessionmaker(bind=engine)
        session = Session()
        
        # Discover all tables in the database
        result = session.execute(text("""
            SELECT tablename FROM pg_tables 
            WHERE schemaname = 'public' 
            AND tablename NOT LIKE 'pg_%' 
            AND tablename NOT LIKE 'sql_%'
            ORDER BY tablename
        """))
        
        all_tables = [row[0] for row in result.fetchall()]
        
        # Define known dependency order, but include any additional tables
        known_order = [
            'call_trigger_log',      # Depends on call_sessions (discovered dependency)
            'call_status_updates',   # Depends on call_sessions
            'customer_events',       # Depends on customers (discovered table)
            'call_sessions',         # Depends on customers, loans, file_uploads, upload_rows
            'upload_rows',           # Depends on file_uploads, customers, loans
            'loans',                 # Depends on customers
            'file_uploads',          # Root table (no dependencies)
            'customers'              # Root table (no dependencies)
        ]
        
        # Add any additional tables not in known order to the beginning (safest approach)
        additional_tables = [table for table in all_tables if table not in known_order]
        table_names = additional_tables + known_order
        
        # Only include tables that actually exist
        table_names = [table for table in table_names if table in all_tables]
        
        if additional_tables:
            print(f"   📋 Discovered additional tables: {', '.join(additional_tables)}")
        print(f"   📋 Will delete from {len(table_names)} tables in dependency order")
        
        # Disable foreign key constraints temporarily (for PostgreSQL)
        session.execute(text("SET session_replication_role = replica;"))
        
        # Delete data from each table
        total_deleted = 0
        for table_name in table_names:
            try:
                result = session.execute(text(f"DELETE FROM {table_name}"))
                deleted_count = result.rowcount
                total_deleted += deleted_count
                print(f"   ✓ Deleted {deleted_count} records from '{table_name}'")
            except Exception as e:
                print(f"   ⚠️  Could not delete from '{table_name}': {e}")
        
        # Re-enable foreign key constraints
        session.execute(text("SET session_replication_role = DEFAULT;"))
        
        # Reset auto-increment sequences (UUID tables don't need this, but included for completeness)
        try:
            # For UUID primary keys, we don't typically need to reset sequences
            # But we can check if any sequences exist and reset them
            sequence_reset_queries = [
                "SELECT setval(seq.relname, 1, false) FROM pg_class seq WHERE seq.relkind = 'S';",
            ]
            for query in sequence_reset_queries:
                try:
                    session.execute(text(query))
                except:
                    pass  # Sequences might not exist
            print("   ✓ Reset sequence counters (if any)")
        except Exception as e:
            # Sequences might not exist, that's okay for UUID tables
            pass
        
        # Commit all changes
        session.commit()
        session.close()
        
        print(f"✅ PostgreSQL wipe completed! Total records deleted: {total_deleted}")
        return True
        
    except Exception as e:
        print(f"❌ Error wiping PostgreSQL database: {e}")
        return False

def wipe_redis_data():
    """Wipe all data from Redis cache"""
    print("\n🗑️  Wiping Redis Cache...")
    print("-" * 40)
    
    try:
        # Connect to Redis using URL or individual parameters
        redis_url = os.getenv('REDIS_URL')
        
        if redis_url:
            # Use Redis URL if provided
            r = redis.from_url(redis_url, decode_responses=True)
        else:
            # Fallback to individual parameters
            redis_host = os.getenv('REDIS_HOST', 'localhost')
            redis_port = int(os.getenv('REDIS_PORT', 6379))
            redis_db = int(os.getenv('REDIS_DB', 0))
            redis_password = os.getenv('REDIS_PASSWORD', None)
            
            r = redis.Redis(
                host=redis_host, 
                port=redis_port, 
                db=redis_db,
                password=redis_password,
                decode_responses=True
            )
        
        # Test connection
        r.ping()
        
        # Get all keys
        all_keys = r.keys('*')
        
        if all_keys:
            # Show categories of keys being deleted
            key_categories = {}
            for key in all_keys:
                if key.startswith('websocket_'):
                    key_categories['WebSocket Sessions'] = key_categories.get('WebSocket Sessions', 0) + 1
                elif key.startswith('call_'):
                    key_categories['Call Sessions'] = key_categories.get('Call Sessions', 0) + 1
                elif key.startswith('customer_'):
                    key_categories['Customer Data'] = key_categories.get('Customer Data', 0) + 1
                elif key.startswith('temp_'):
                    key_categories['Temporary Data'] = key_categories.get('Temporary Data', 0) + 1
                else:
                    key_categories['Other'] = key_categories.get('Other', 0) + 1
            
            # Show breakdown
            for category, count in key_categories.items():
                print(f"   • {category}: {count} keys")
            
            # Delete all keys
            deleted_count = r.delete(*all_keys)
            print(f"   ✓ Deleted {deleted_count} Redis keys total")
        else:
            print("   ✓ Redis cache was already empty")
        
        print("✅ Redis wipe completed!")
        return True
        
    except redis.ConnectionError:
        print("⚠️  Redis not available - skipping Redis wipe")
        return True  # Not critical if Redis is not running
    except Exception as e:
        print(f"❌ Error wiping Redis cache: {e}")
        return False

def recreate_database_schema():
    """Recreate all database tables (fresh schema)"""
    print("\n🔄 Recreating Database Schema...")
    print("-" * 40)
    
    try:
        # Initialize database connection directly
        DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://postgres:IntalksAI07@db-voice-agent.cviea4aicss0.ap-south-1.rds.amazonaws.com:5432/db-voice-agent')
        engine = create_engine(DATABASE_URL, echo=False)
        
        # Drop all tables with CASCADE to handle dependencies
        print("   ⚠️  Dropping all existing tables with CASCADE...")
        try:
            Base.metadata.drop_all(engine, checkfirst=True)
            print("   ✓ Dropped all existing tables")
        except Exception as e:
            # If normal drop fails, try CASCADE approach
            print(f"   ⚠️  Normal drop failed: {e}")
            print("   🔧 Trying CASCADE drop for remaining tables...")
            
            Session = sessionmaker(bind=engine)
            session = Session()
            
            # Get all table names that still exist
            result = session.execute(text("""
                SELECT tablename FROM pg_tables 
                WHERE schemaname = 'public' 
                AND tablename NOT LIKE 'pg_%' 
                AND tablename NOT LIKE 'sql_%'
            """))
            
            remaining_tables = [row[0] for row in result.fetchall()]
            
            if remaining_tables:
                # Drop remaining tables with CASCADE
                for table in remaining_tables:
                    try:
                        session.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
                        print(f"   ✓ Dropped {table} with CASCADE")
                    except Exception as drop_error:
                        print(f"   ⚠️  Could not drop {table}: {drop_error}")
                
                session.commit()
            
            session.close()
        
        # Recreate all tables
        Base.metadata.create_all(engine)
        print("   ✓ Created fresh database schema")
        
        print("✅ Database schema recreation completed!")
        return True
        
    except Exception as e:
        print(f"❌ Error recreating database schema: {e}")
        return False

def main():
    """Main wipe function"""
    print("🧹 Voice Assistant Database Wipe Script")
    print("=" * 50)
    
    # Check for dry-run mode
    dry_run = '--dry-run' in sys.argv or '-n' in sys.argv
    if dry_run:
        print("🔍 DRY RUN MODE - No data will be deleted")
        print("=" * 50)
    
    # Show current database status
    show_current_data_status()
    
    if dry_run:
        print("\n✅ Dry run completed. No data was modified.")
        print("To actually wipe data, run the script without --dry-run flag.")
        sys.exit(0)
    
    # Check if user confirmed the operation
    if not confirm_wipe():
        sys.exit(0)
    
    print("\n🚀 Starting data wipe operation...")
    
    # Track success of each operation
    operations = []
    
    # 1. Wipe PostgreSQL data
    postgres_success = wipe_postgresql_data()
    operations.append(("PostgreSQL Data Wipe", postgres_success))
    
    # 2. Wipe Redis data
    redis_success = wipe_redis_data()
    operations.append(("Redis Cache Wipe", redis_success))
    
    # 3. Recreate database schema (optional, ensures clean state)
    schema_success = recreate_database_schema()
    operations.append(("Database Schema Recreation", schema_success))
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 WIPE OPERATION SUMMARY")
    print("=" * 50)
    
    all_successful = True
    for operation, success in operations:
        status = "✅ SUCCESS" if success else "❌ FAILED"
        print(f"{operation}: {status}")
        if not success:
            all_successful = False
    
    print("=" * 50)
    
    if all_successful:
        print("🎉 ALL DATA SUCCESSFULLY WIPED!")
        print("The database is now clean and ready for fresh data.")
        
        # Show final status
        print("\n📊 Final Database Status:")
        show_current_data_status()
    else:
        print("⚠️  Some operations failed. Please check the errors above.")
        sys.exit(1)

if __name__ == "__main__":
    # Show usage if help requested
    if '--help' in sys.argv or '-h' in sys.argv:
        print("Usage: python wipe_data.py [OPTIONS]")
        print("\nOptions:")
        print("  --dry-run, -n    Show what would be deleted without actually deleting")
        print("  --help, -h       Show this help message")
        print("\nWarning: This script will permanently delete ALL data!")
        sys.exit(0)
    
    main()
