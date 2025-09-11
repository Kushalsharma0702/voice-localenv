#!/usr/bin/env python3
"""
Insert Sample Data for Testing Duplicate Customer Fix
Creates test data with customer "Haku" for today and yesterday
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from decimal import Decimal

# Add current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from database.schemas import get_session, Customer, Loan, FileUpload
from services.enhanced_csv_processor import EnhancedCSVProcessor
import pytz

# IST timezone setup
IST = pytz.timezone('Asia/Kolkata')

def create_test_data():
    """Create test data with Haku customer for today and yesterday"""
    
    print("🧪 Creating Test Data for Date Filtering")
    print("=" * 50)
    
    session = get_session()
    csv_processor = EnhancedCSVProcessor(session)
    
    try:
        # Clean up any existing Haku data first
        existing_customer = session.query(Customer).filter(Customer.full_name == "Haku").first()
        if existing_customer:
            print("🧹 Cleaning up existing Haku data...")
            # Delete related loans first
            existing_loans = session.query(Loan).filter(Loan.customer_id == existing_customer.id).all()
            for loan in existing_loans:
                session.delete(loan)
            session.delete(existing_customer)
            
            # Clean up existing file uploads
            existing_uploads = session.query(FileUpload).filter(
                FileUpload.filename.like("haku_%")
            ).all()
            for upload in existing_uploads:
                session.delete(upload)
            
            session.commit()
        
        # Get today and yesterday dates in IST, convert to UTC for database storage
        today_ist = datetime.now(IST).replace(hour=10, minute=0, second=0, microsecond=0)
        yesterday_ist = today_ist - timedelta(days=1)
        
        today_utc = today_ist.astimezone(pytz.UTC).replace(tzinfo=None)
        yesterday_utc = yesterday_ist.astimezone(pytz.UTC).replace(tzinfo=None)
        
        print(f"📅 Today IST: {today_ist}")
        print(f"📅 Yesterday IST: {yesterday_ist}")
        print(f"📅 Today UTC (for DB): {today_utc}")
        print(f"📅 Yesterday UTC (for DB): {yesterday_utc}")
        
        # STEP 1: Create customer with yesterday's date (first upload)
        haku_fingerprint = csv_processor.compute_customer_fingerprint("Haku", "+919876543210")
        
        haku_customer = Customer(
            fingerprint=haku_fingerprint,
            full_name="Haku",
            primary_phone="+919876543210",
            state="Karnataka",
            first_uploaded_at=yesterday_utc,  # Customer first uploaded yesterday
            created_at=yesterday_utc,
            updated_at=yesterday_utc
        )
        
        session.add(haku_customer)
        session.flush()  # Get the customer ID
        
        print(f"✅ Created customer 'Haku' with yesterday's date")
        print(f"   Customer ID: {haku_customer.id}")
        print(f"   First uploaded: {haku_customer.first_uploaded_at}")
        
        # STEP 2: Create loan for Haku from yesterday's upload
        haku_loan_yesterday = Loan(
            customer_id=haku_customer.id,
            loan_id="HAKU_LOAN_001",
            principal_amount=Decimal("100000"),
            outstanding_amount=Decimal("85000"),
            due_amount=Decimal("5000"),
            next_due_date=datetime.now().date(),
            status="active",
            cluster="Test Cluster",
            branch="Test Branch",
            branch_contact_number="+918012345678",
            employee_name="Test Employee",
            employee_id="EMP999",
            employee_contact_number="+919012345678",
            created_at=yesterday_utc,
            updated_at=yesterday_utc
        )
        
        session.add(haku_loan_yesterday)
        print(f"✅ Created loan for Haku (yesterday): {haku_loan_yesterday.loan_id}")
        
        # STEP 3: Create another loan for Haku from today's upload (different loan)
        haku_loan_today = Loan(
            customer_id=haku_customer.id,
            loan_id="HAKU_LOAN_002",  # Different loan ID
            principal_amount=Decimal("150000"),
            outstanding_amount=Decimal("120000"),
            due_amount=Decimal("8000"),
            next_due_date=datetime.now().date() + timedelta(days=30),
            status="active",
            cluster="Test Cluster",
            branch="Test Branch",
            branch_contact_number="+918012345678",
            employee_name="Test Employee",
            employee_id="EMP999",
            employee_contact_number="+919012345678",
            created_at=today_utc,
            updated_at=today_utc
        )
        
        session.add(haku_loan_today)
        print(f"✅ Created loan for Haku (today): {haku_loan_today.loan_id}")
        
        # STEP 4: Create FileUpload record for yesterday
        yesterday_file_upload = FileUpload(
            filename="haku_yesterday_upload.csv",
            original_filename="haku_yesterday_upload.csv",
            uploaded_by="test_user",
            total_records=1,
            processed_records=1,
            success_records=1,  # New customer created
            failed_records=0,
            status="completed",
            uploaded_at=yesterday_utc
        )
        
        session.add(yesterday_file_upload)
        print(f"✅ Created FileUpload record for yesterday")
        
        # STEP 5: Create FileUpload record for today (same customer, new loan)
        today_file_upload = FileUpload(
            filename="haku_today_upload.csv", 
            original_filename="haku_today_upload.csv",
            uploaded_by="test_user",
            total_records=1,
            processed_records=1,
            success_records=0,  # No new customers (existing customer)
            failed_records=0,
            status="completed",
            uploaded_at=today_utc
        )
        
        session.add(today_file_upload)
        print(f"✅ Created FileUpload record for today")
        
        # STEP 6: Update customer's updated_at to today (to simulate processing in today's upload)
        # This preserves first_uploaded_at but shows the customer was processed today too
        haku_customer.updated_at = today_utc
        
        # Commit all changes
        session.commit()
        
        print("\n🎉 Test data created successfully!")
        print("\n📊 Summary:")
        print(f"   • Customer 'Haku' with first_uploaded_at: {yesterday_ist.date()} (preserved)")
        print(f"   • Customer 'Haku' with updated_at: {today_ist.date()} (shows recent activity)")
        print(f"   • Loan from yesterday: HAKU_LOAN_001 with ₹85,000 outstanding")
        print(f"   • Loan from today: HAKU_LOAN_002 with ₹120,000 outstanding")
        print(f"   • FileUpload for yesterday: haku_yesterday_upload.csv (1 new customer)")
        print(f"   • FileUpload for today: haku_today_upload.csv (0 new customers, 1 existing)")
        print("\n🧪 Expected behavior:")
        print(f"   • Filter 'Yesterday' → Should show 'Haku' customer (original upload)")
        print(f"   • Filter 'Today' → Should show 'Haku' customer (reprocessed with new loan)")
        print(f"   • Customer preserves original first_uploaded_at date")
        print(f"   • Both loans visible for the same customer")
        print(f"   • Batch uploads → Yesterday: 1 file, Today: 1 file")
        
        return True
        
    except Exception as e:
        session.rollback()
        print(f"❌ Error creating test data: {e}")
        return False
        
    finally:
        session.close()

def verify_test_data():
    """Verify the test data was created correctly"""
    
    print("\n🔍 Verifying Test Data")
    print("=" * 30)
    
    session = get_session()
    
    try:
        # Check customer
        haku = session.query(Customer).filter(Customer.full_name == "Haku").first()
        if haku:
            first_uploaded_ist = haku.first_uploaded_at.replace(tzinfo=pytz.UTC).astimezone(IST)
            updated_ist = haku.updated_at.replace(tzinfo=pytz.UTC).astimezone(IST)
            print(f"✅ Customer found: {haku.full_name}")
            print(f"   Phone: {haku.primary_phone}")
            print(f"   First uploaded: {first_uploaded_ist} IST (preserved)")
            print(f"   Last updated: {updated_ist} IST (recent activity)")
            print(f"   State: {haku.state}")
        else:
            print("❌ Customer 'Haku' not found")
            return False
        
        # Check loans
        loans = session.query(Loan).filter(Loan.customer_id == haku.id).order_by(Loan.created_at).all()
        print(f"✅ Found {len(loans)} loan(s) for Haku:")
        for i, loan in enumerate(loans, 1):
            created_ist = loan.created_at.replace(tzinfo=pytz.UTC).astimezone(IST)
            print(f"   {i}. {loan.loan_id} - ₹{loan.outstanding_amount} (created {created_ist.date()})")
        
        # Check file uploads
        file_uploads = session.query(FileUpload).filter(
            FileUpload.filename.like("haku_%")
        ).order_by(FileUpload.uploaded_at).all()
        
        print(f"✅ Found {len(file_uploads)} file upload records:")
        for upload in file_uploads:
            ist_date = upload.uploaded_at.replace(tzinfo=pytz.UTC).astimezone(IST)
            print(f"   • {upload.filename} - {ist_date.date()} IST")
            print(f"     Success: {upload.success_records}, Processed: {upload.processed_records}")
        
        # Check what date filtering should show
        print(f"\n🔍 Date Filtering Logic:")
        print(f"   • Customer first uploaded: {first_uploaded_ist.date()}")
        print(f"   • Customer last updated: {updated_ist.date()}")
        print(f"   • Yesterday filter: Should show Haku (original upload)")
        print(f"   • Today filter: Should show Haku (recent activity/new loan)")
        
        return True
        
    except Exception as e:
        print(f"❌ Error verifying test data: {e}")
        return False
        
    finally:
        session.close()

def main():
    """Main function"""
    print("🧪 Haku Test Data Creator")
    print("=" * 40)
    print("This script creates test data to verify the duplicate customer fix")
    print("Customer 'Haku' will be created with yesterday's upload date")
    print("=" * 40)
    
    # Create test data
    success = create_test_data()
    
    if success:
        # Verify test data
        verify_test_data()
        
        print("\n🚀 Ready for Testing!")
        print("=" * 20)
        print("1. Start your server: python main.py")
        print("2. Open dashboard: http://localhost:8000")
        print("3. Test date filters:")
        print("   • 'Yesterday' filter → Should show Haku")
        print("   • 'Today' filter → Should NOT show Haku")
        print("4. Check batch uploads for both dates")
    else:
        print("\n❌ Failed to create test data")

if __name__ == "__main__":
    main()
