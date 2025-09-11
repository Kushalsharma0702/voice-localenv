#!/usr/bin/env python3
"""
Test Script to Verify Duplicate Customer Handling
Tests that existing customers preserve their first_uploaded_at date
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from database.schemas import get_session, Customer, Loan
from services.enhanced_csv_processor import EnhancedCSVProcessor, CSVRow, ProcessingStatus
import pytz

# IST timezone setup
IST = pytz.timezone('Asia/Kolkata')

def test_duplicate_customer_handling():
    """Test that duplicate customers preserve their original upload date"""
    
    print("🧪 Testing Duplicate Customer Handling")
    print("=" * 50)
    
    session = get_session()
    
    try:
        # Step 1: Create a test customer with yesterday's date
        yesterday = datetime.now(IST) - timedelta(days=1)
        yesterday_utc = yesterday.astimezone(pytz.UTC).replace(tzinfo=None)
        
        test_phone = "+919999999999"
        test_name = "Test Customer Duplicate"
        
        # Clean up any existing test customer
        existing_test = session.query(Customer).filter(Customer.primary_phone == test_phone).first()
        if existing_test:
            session.delete(existing_test)
            session.commit()
        
        # Create test customer with yesterday's date
        from services.enhanced_csv_processor import EnhancedCSVProcessor
        csv_processor = EnhancedCSVProcessor(session)
        fingerprint = csv_processor.compute_customer_fingerprint(test_name, test_phone)
        
        test_customer = Customer(
            fingerprint=fingerprint,
            full_name=test_name,
            primary_phone=test_phone,
            state="Test State",
            first_uploaded_at=yesterday_utc
        )
        session.add(test_customer)
        session.commit()
        session.refresh(test_customer)
        
        print(f"✅ Created test customer with yesterday's date: {test_customer.first_uploaded_at}")
        
        # Step 2: Process the same customer data through CSV processor (simulating duplicate upload)
        csv_processor = EnhancedCSVProcessor(session)
        
        # Create a CSV row with the same customer data
        csv_row = CSVRow(
            line_number=1,
            raw_data={"name": test_name, "phone": "9999999999"},
            customer_name=test_name,
            phone_normalized=test_phone,
            loan_id_text="LOAN999",
            amount=None,
            due_date=None,
            state="Updated State",  # Different state to test update
            cluster="Test Cluster",
            branch="Test Branch",
            branch_contact_number="",
            employee_name="",
            employee_id="",
            employee_contact="",
            last_paid_date=None,
            last_paid_amount=None,
            due_amount=None,
            record_fingerprint="test_fingerprint"
        )
        
        # Step 3: Process the "duplicate" customer
        updated_customer, is_new = csv_processor.create_or_update_customer(csv_row)
        session.commit()
        
        print(f"✅ Processed duplicate customer - Is New: {is_new}")
        print(f"✅ Customer ID: {updated_customer.id}")
        print(f"✅ Original upload date: {test_customer.first_uploaded_at}")
        print(f"✅ After processing date: {updated_customer.first_uploaded_at}")
        print(f"✅ State updated: {updated_customer.state}")
        
        # Step 4: Verify the first_uploaded_at date was preserved
        if updated_customer.first_uploaded_at == yesterday_utc:
            print("🎉 SUCCESS: first_uploaded_at date was preserved!")
            return True
        else:
            print(f"❌ FAILED: first_uploaded_at date was changed from {yesterday_utc} to {updated_customer.first_uploaded_at}")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False
        
    finally:
        # Clean up test data
        try:
            test_customer = session.query(Customer).filter(Customer.primary_phone == test_phone).first()
            if test_customer:
                session.delete(test_customer)
                session.commit()
                print("🧹 Cleaned up test data")
        except Exception as e:
            print(f"⚠️ Cleanup warning: {e}")
        
        session.close()

def check_existing_customer_dates():
    """Check the distribution of customer upload dates"""
    
    print("\n📊 Current Customer Upload Date Distribution")
    print("=" * 50)
    
    session = get_session()
    
    try:
        from collections import defaultdict
        
        customers = session.query(Customer).all()
        date_counts = defaultdict(int)
        
        for customer in customers:
            if customer.first_uploaded_at:
                # Convert to IST for display
                ist_date = customer.first_uploaded_at.replace(tzinfo=pytz.UTC).astimezone(IST).date()
                date_counts[ist_date] += 1
        
        print(f"📋 Total customers: {len(customers)}")
        print("📅 Upload date distribution:")
        
        for date_key in sorted(date_counts.keys(), reverse=True):
            count = date_counts[date_key]
            print(f"   {date_key}: {count} customers")
        
        return date_counts
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return {}
        
    finally:
        session.close()

def main():
    """Main test function"""
    print("🔧 Duplicate Customer Upload Date Fix - Test Suite")
    print("=" * 60)
    
    # Test 1: Check existing customer dates
    check_existing_customer_dates()
    
    # Test 2: Test duplicate handling
    success = test_duplicate_customer_handling()
    
    if success:
        print("\n🎉 All tests passed! Duplicate customer handling is working correctly.")
    else:
        print("\n❌ Tests failed! There may be an issue with the fix.")

if __name__ == "__main__":
    main()
