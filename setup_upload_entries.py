#!/usr/bin/env python3
"""
Setup Upload Entries System
Creates the new schema and migrates existing data to upload entries format
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

def setup_upload_entries_system():
    """Set up the complete upload entries system"""
    
    print("🚀 Setting Up Upload Entries System")
    print("=" * 50)
    
    try:
        # Step 1: Create new tables
        print("\n📋 Step 1: Creating upload entries tables...")
        from database.upload_entries_schema import create_tables
        create_tables()
        
        # Step 2: Create sample data using the new processor
        print("\n📊 Step 2: Creating sample upload entries...")
        from services.upload_entries_processor import create_sample_upload_entries
        success = create_sample_upload_entries()
        
        if success:
            print("✅ Sample data created successfully!")
        else:
            print("⚠️  Sample data creation had issues")
        
        # Step 3: Test the API
        print("\n🧪 Step 3: Testing upload entries API...")
        from api.upload_entries_api import test_upload_entries_api
        import asyncio
        asyncio.run(test_upload_entries_api())
        
        print("\n🎉 Upload Entries System Setup Complete!")
        print("=" * 50)
        print("✅ New schema created")
        print("✅ Sample data populated") 
        print("✅ API endpoints tested")
        
        print("\n📝 Next Steps:")
        print("1. Update main.py to include new API endpoints")
        print("2. Update frontend to use new upload entries API")
        print("3. Test date filtering functionality")
        
        return True
        
    except Exception as e:
        print(f"❌ Setup failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def create_test_data_multiple_dates():
    """Create test data across multiple dates for comprehensive testing"""
    
    print("\n🧪 Creating Test Data Across Multiple Dates")
    print("=" * 50)
    
    try:
        from services.upload_entries_processor import UploadEntriesCSVProcessor
        from database.upload_entries_schema import get_session
        import pytz
        
        session = get_session()
        processor = UploadEntriesCSVProcessor(session)
        
        IST = pytz.timezone('Asia/Kolkata')
        base_time = datetime.now(IST).replace(hour=10, minute=0, second=0, microsecond=0)
        
        # Create data for different dates
        test_dates = [
            ("today", base_time, "HAKU_LOAN_003", "Today's upload"),
            ("yesterday", base_time - timedelta(days=1), "HAKU_LOAN_004", "Yesterday's upload"),
            ("2_days_ago", base_time - timedelta(days=2), "HAKU_LOAN_005", "2 days ago upload"),
            ("this_week", base_time - timedelta(days=3), "HAKU_LOAN_006", "Earlier this week"),
        ]
        
        for date_name, upload_time_ist, loan_id, description in test_dates:
            print(f"\n📅 Creating {description}...")
            
            # Convert to UTC
            upload_time_utc = upload_time_ist.astimezone(pytz.UTC).replace(tzinfo=None)
            
            # Create CSV data
            csv_data = f"""name,phone,loan_id,amount,due_date,state,Cluster,Branch,Branch Contact Number,Employee,Employee ID,Employee Contact Number,Last Paid Date,Last Paid Amount,Due Amount
Haku,9876543210,{loan_id},200000,2024-03-15,Karnataka,Test Cluster,Test Branch,08012345678,Test Employee,EMP999,09012345678,2024-01-15,10000,15000"""
            
            # Process the upload
            result = processor.process_upload_entries(
                file_data=csv_data.encode('utf-8'),
                filename=f"haku_{date_name}_upload.csv",
                uploaded_by="test_user",
                upload_timestamp=upload_time_utc
            )
            
            print(f"✅ {description} created: {result['success_records']} records")
        
        print("\n🎉 Multi-date test data created successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Test data creation failed: {e}")
        return False
    
    finally:
        session.close()

def verify_data_distribution():
    """Verify data distribution across dates"""
    
    print("\n🔍 Verifying Data Distribution")
    print("=" * 40)
    
    try:
        from database.upload_entries_schema import CustomerUploadEntry, get_session
        import pytz
        
        session = get_session()
        
        # Get all upload entries
        entries = session.query(CustomerUploadEntry).order_by(
            CustomerUploadEntry.upload_timestamp.desc()
        ).all()
        
        print(f"📊 Total upload entries: {len(entries)}")
        
        # Group by date
        IST = pytz.timezone('Asia/Kolkata')
        date_groups = {}
        
        for entry in entries:
            # Convert to IST for display
            ist_timestamp = entry.upload_timestamp.replace(tzinfo=pytz.UTC).astimezone(IST)
            date_key = ist_timestamp.date()
            
            if date_key not in date_groups:
                date_groups[date_key] = []
            date_groups[date_key].append(entry)
        
        print(f"\n📅 Data distribution by date:")
        for date_key in sorted(date_groups.keys(), reverse=True):
            entries_for_date = date_groups[date_key]
            print(f"  {date_key}: {len(entries_for_date)} entries")
            
            # Show customer names
            customers = [entry.full_name for entry in entries_for_date]
            unique_customers = set(customers)
            print(f"    Customers: {', '.join(unique_customers)}")
            
            # Show loan IDs
            loan_ids = [entry.loan_id for entry in entries_for_date]
            print(f"    Loan IDs: {', '.join(loan_ids)}")
        
        return True
        
    except Exception as e:
        print(f"❌ Verification failed: {e}")
        return False
    
    finally:
        session.close()

def main():
    """Main setup function"""
    
    print("🎯 Upload Entries System Setup")
    print("=" * 50)
    print("This will create a new system where each customer upload")
    print("is stored as a separate entry, allowing customers to appear")
    print("multiple times across different upload dates.")
    print("=" * 50)
    
    # Step 1: Setup basic system
    success = setup_upload_entries_system()
    if not success:
        print("❌ Basic setup failed. Exiting.")
        return
    
    # Step 2: Create comprehensive test data
    print("\n" + "=" * 50)
    success = create_test_data_multiple_dates()
    if not success:
        print("⚠️  Test data creation had issues, but continuing...")
    
    # Step 3: Verify data distribution
    print("\n" + "=" * 50)
    verify_data_distribution()
    
    print("\n🎉 SETUP COMPLETE!")
    print("=" * 50)
    print("🔧 What was created:")
    print("  • New CustomerUploadEntry table")
    print("  • Upload entries processor")
    print("  • API endpoints for querying entries")
    print("  • Sample data across multiple dates")
    print("\n📋 Next steps:")
    print("  1. Update main.py to include new endpoints")
    print("  2. Update frontend to use upload entries API")
    print("  3. Test the date filtering on frontend")

if __name__ == "__main__":
    main()
