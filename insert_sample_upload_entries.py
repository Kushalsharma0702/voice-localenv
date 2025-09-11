#!/usr/bin/env python3
"""
Insert Sample Upload Entries Script
Creates individual upload entries for testing the new date filtering approach
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from decimal import Decimal
import pytz

# Add current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from database.schemas import get_session, Customer, Loan, FileUpload

# IST timezone setup
IST = pytz.timezone('Asia/Kolkata')

def create_separate_upload_entries():
    """
    Create separate customer/loan entries for each upload date
    This simulates the behavior you want - same customer appearing multiple times
    """
    
    print("🧪 Creating Separate Upload Entries for Date Testing")
    print("=" * 60)
    
    session = get_session()
    
    try:
        # Clean up existing Haku data
        print("🧹 Cleaning up existing test data...")
        
        # Delete existing customers named Haku
        existing_customers = session.query(Customer).filter(Customer.full_name == "Haku").all()
        for customer in existing_customers:
            # Delete their loans first
            for loan in customer.loans:
                session.delete(loan)
            session.delete(customer)
        
        # Delete existing file uploads with Haku
        existing_uploads = session.query(FileUpload).filter(
            FileUpload.filename.like("%haku%")
        ).all()
        for upload in existing_uploads:
            session.delete(upload)
        
        session.commit()
        print("✅ Cleanup completed")
        
        # Define upload dates
        today_ist = datetime.now(IST).replace(hour=10, minute=0, second=0, microsecond=0)
        yesterday_ist = today_ist - timedelta(days=1)
        two_days_ago_ist = today_ist - timedelta(days=2)
        
        # Convert to UTC for database storage
        upload_dates = [
            ("yesterday", yesterday_ist.astimezone(pytz.UTC).replace(tzinfo=None)),
            ("today", today_ist.astimezone(pytz.UTC).replace(tzinfo=None)),
            ("two_days_ago", two_days_ago_ist.astimezone(pytz.UTC).replace(tzinfo=None))
        ]
        
        created_entries = []
        
        # Define unique phone numbers for each entry
        phone_numbers = {
            "yesterday": "+919876543210",
            "today": "+919876543211", 
            "two_days_ago": "+919876543212"
        }
        
        for date_name, upload_date_utc in upload_dates:
            print(f"\n📅 Creating entry for {date_name}...")
            
            # Create a unique customer entry for each upload date
            # This is the key - separate customer records for each upload
            customer = Customer(
                fingerprint=f"haku_upload_{date_name}",  # Unique fingerprint per upload
                full_name="Haku",
                primary_phone=phone_numbers[date_name],  # Unique phone for each entry
                state="Karnataka",
                first_uploaded_at=upload_date_utc,  # This will be the filter date
                created_at=upload_date_utc,
                updated_at=upload_date_utc
            )
            
            session.add(customer)
            session.flush()  # Get the ID
            
            # Create a loan for this customer entry
            loan = Loan(
                customer_id=customer.id,
                loan_id=f"HAKU_LOAN_{date_name.upper()}",
                principal_amount=Decimal("100000"),
                outstanding_amount=Decimal("85000") + Decimal(date_name == "today" and "15000" or "0"),
                due_amount=Decimal("5000") + Decimal(date_name == "today" and "3000" or "0"),
                next_due_date=datetime.now().date(),
                status="active",
                cluster="Test Cluster",
                branch="Test Branch",
                branch_contact_number="+918012345678",
                employee_name="Test Employee",
                employee_id="EMP999",
                employee_contact_number="+919012345678",
                created_at=upload_date_utc,
                updated_at=upload_date_utc
            )
            
            session.add(loan)
            
            # Create a file upload record for this date
            file_upload = FileUpload(
                filename=f"haku_{date_name}_upload.csv",
                original_filename=f"haku_{date_name}_upload.csv",
                uploaded_by="test_user",
                total_records=1,
                processed_records=1,
                success_records=1,
                failed_records=0,
                status="completed",
                uploaded_at=upload_date_utc
            )
            
            session.add(file_upload)
            
            created_entries.append({
                'date_name': date_name,
                'upload_date': upload_date_utc,
                'customer_id': str(customer.id),
                'loan_id': loan.loan_id,
                'file_upload': file_upload.filename
            })
            
            print(f"✅ Created entry for {date_name}")
            print(f"   Customer ID: {customer.id}")
            print(f"   Loan ID: {loan.loan_id}")
            print(f"   Upload date: {upload_date_utc}")
        
        # Commit all changes
        session.commit()
        
        print(f"\n🎉 Successfully created {len(created_entries)} separate upload entries!")
        
        # Display summary
        print("\n📊 Summary of created entries:")
        for entry in created_entries:
            print(f"  • {entry['date_name']}: {entry['loan_id']} - {entry['file_upload']}")
        
        print("\n🧪 Expected behavior:")
        print("  • Filter 'Yesterday' → Should show Haku (yesterday entry)")
        print("  • Filter 'Today' → Should show Haku (today entry)")
        print("  • Filter 'Two days ago' → Should show Haku (two days ago entry)")
        print("  • Each filter shows only entries from that specific date")
        print("  • Total customers will be 3 (separate entries for same person)")
        
        return True
        
    except Exception as e:
        session.rollback()
        print(f"❌ Error creating upload entries: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        session.close()

def verify_separate_entries():
    """Verify that separate entries were created correctly"""
    
    print("\n🔍 Verifying Separate Upload Entries")
    print("=" * 40)
    
    session = get_session()
    
    try:
        # Get all Haku customers
        haku_customers = session.query(Customer).filter(Customer.full_name == "Haku").all()
        
        print(f"📊 Found {len(haku_customers)} Haku customer entries")
        
        # Group by upload date
        date_groups = {}
        
        for customer in haku_customers:
            # Convert to IST for display
            upload_date_ist = customer.first_uploaded_at.replace(tzinfo=pytz.UTC).astimezone(IST)
            date_key = upload_date_ist.date()
            
            if date_key not in date_groups:
                date_groups[date_key] = []
            
            date_groups[date_key].append({
                'customer_id': str(customer.id),
                'fingerprint': customer.fingerprint,
                'loans': [loan.loan_id for loan in customer.loans],
                'upload_time': upload_date_ist
            })
        
        print(f"\n📅 Entries by upload date:")
        for date_key in sorted(date_groups.keys(), reverse=True):
            entries = date_groups[date_key]
            print(f"  {date_key}: {len(entries)} entry(ies)")
            
            for entry in entries:
                print(f"    • ID: {entry['customer_id'][:8]}...")
                print(f"      Fingerprint: {entry['fingerprint']}")
                print(f"      Loans: {', '.join(entry['loans'])}")
                print(f"      Upload time: {entry['upload_time']}")
        
        # Test date filtering logic
        print(f"\n🧪 Testing date filtering logic:")
        
        # Today's entries
        today = datetime.now(IST).date()
        today_entries = [entry for date_key, entries in date_groups.items() 
                        if date_key == today for entry in entries]
        print(f"  Today ({today}): {len(today_entries)} entries")
        
        # Yesterday's entries
        yesterday = today - timedelta(days=1)
        yesterday_entries = [entry for date_key, entries in date_groups.items() 
                           if date_key == yesterday for entry in entries]
        print(f"  Yesterday ({yesterday}): {len(yesterday_entries)} entries")
        
        # Two days ago entries
        two_days_ago = today - timedelta(days=2)
        two_days_ago_entries = [entry for date_key, entries in date_groups.items() 
                              if date_key == two_days_ago for entry in entries]
        print(f"  Two days ago ({two_days_ago}): {len(two_days_ago_entries)} entries")
        
        return True
        
    except Exception as e:
        print(f"❌ Verification failed: {e}")
        return False
        
    finally:
        session.close()

def main():
    """Main function"""
    
    print("🎯 Separate Upload Entries Creator")
    print("=" * 50)
    print("This creates separate customer records for each upload date,")
    print("allowing the same person to appear in multiple date filters.")
    print("=" * 50)
    
    # Create separate entries
    success = create_separate_upload_entries()
    
    if success:
        # Verify the entries
        verify_separate_entries()
        
        print("\n🚀 Ready for Testing!")
        print("=" * 30)
        print("1. Start your server: python main.py")
        print("2. Open dashboard: http://localhost:8000")
        print("3. Test date filters:")
        print("   • 'Yesterday' → Should show Haku")
        print("   • 'Today' → Should show Haku")
        print("   • Both are separate database entries")
    else:
        print("\n❌ Failed to create test data")

if __name__ == "__main__":
    main()
