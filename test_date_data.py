#!/usr/bin/env python3
"""
Test Data Script with Various Dates
Creates test customers with different upload dates to test date filtering functionality
"""
import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# Add current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from database.schemas import get_session, Customer, Loan
import pytz

# IST timezone setup
IST = pytz.timezone('Asia/Kolkata')

def get_ist_date(days_offset=0):
    """Get IST date with offset"""
    # Get current date in IST and set to a specific time to avoid timezone issues
    ist_now = datetime.now(IST)
    
    # Set to noon IST to avoid any daylight saving or edge case issues
    base_date = ist_now.replace(hour=12, minute=0, second=0, microsecond=0)
    
    # Add the days offset
    target_date = base_date + timedelta(days=days_offset)
    
    return target_date

def create_test_customers():
    """Create test customers with various dates"""
    session = get_session()
    
    try:
        print("🧪 Creating test customers with various dates...")
        print("=" * 50)
        
        # Test data with different dates
        test_data = [
            {
                "name": "Past Customer 1",
                "phone": "+918888888881",
                "days_offset": -7,  # 7 days ago
                "loan_id": "PAST001",
                "amount": 25000,
                "state": "Karnataka"
            },
            {
                "name": "Past Customer 2", 
                "phone": "+918888888882",
                "days_offset": -3,  # 3 days ago
                "loan_id": "PAST002",
                "amount": 35000,
                "state": "Maharashtra"
            },
            {
                "name": "Yesterday Customer 1",
                "phone": "+918888888883",
                "days_offset": -1,  # Yesterday
                "loan_id": "YEST001",
                "amount": 45000,
                "state": "Tamil Nadu"
            },
            {
                "name": "Yesterday Customer 2",
                "phone": "+918888888888",
                "days_offset": -1,  # Yesterday
                "loan_id": "YEST002",
                "amount": 32000,
                "state": "Kerala"
            },
            {
                "name": "Yesterday Customer 3",
                "phone": "+918888888889",
                "days_offset": -1,  # Yesterday
                "loan_id": "YEST003",
                "amount": 28000,
                "state": "Andhra Pradesh"
            },
            {
                "name": "Today Customer 1",
                "phone": "+918888888884",
                "days_offset": 0,   # Today
                "loan_id": "TOD001",
                "amount": 55000,
                "state": "Gujarat"
            },
            {
                "name": "Today Customer 2",
                "phone": "+918888888885",
                "days_offset": 0,   # Today
                "loan_id": "TOD002",
                "amount": 65000,
                "state": "West Bengal"
            },
            {
                "name": "Tomorrow Customer",
                "phone": "+918888888886",
                "days_offset": 1,   # Tomorrow
                "loan_id": "TOM001",
                "amount": 75000,
                "state": "Rajasthan"
            },
            {
                "name": "Future Customer",
                "phone": "+918888888887",
                "days_offset": 5,   # 5 days in future
                "loan_id": "FUT001",
                "amount": 85000,
                "state": "Punjab"
            }
        ]
        
        created_customers = []
        
        for data in test_data:
            # Calculate the target date
            target_date = get_ist_date(data["days_offset"])
            
            print(f"📅 Creating customer for {target_date.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            print(f"   👤 Name: {data['name']}")
            print(f"   📞 Phone: {data['phone']}")
            print(f"   📊 Days offset: {data['days_offset']}")
            print(f"   🕒 Raw target_date: {target_date}")
            print(f"   🌍 Target timezone: {target_date.tzinfo}")
            
            # Create customer
            customer = Customer(
                id=uuid.uuid4(),
                fingerprint=f"test_{data['phone']}_{target_date.timestamp()}",  # Required unique fingerprint
                full_name=data["name"],
                primary_phone=data["phone"],
                state=data["state"],
                first_uploaded_at=target_date,
                created_at=target_date,
                updated_at=target_date
            )
            
            session.add(customer)
            session.flush()  # Get the customer ID
            
            # Create loan
            loan = Loan(
                id=uuid.uuid4(),
                customer_id=customer.id,
                loan_id=data["loan_id"],
                outstanding_amount=data["amount"],
                due_amount=data["amount"] * 0.1,  # 10% due
                status="active",
                cluster="Test Cluster",
                branch="Test Branch",
                branch_contact_number="+911234567890",
                employee_name="Test Employee",
                employee_id="EMP999",
                employee_contact_number="+919876543210",
                created_at=target_date,
                updated_at=target_date
            )
            
            session.add(loan)
            created_customers.append({
                "customer": customer,
                "loan": loan,
                "date": target_date.strftime('%Y-%m-%d %H:%M:%S %Z')
            })
        
        # Commit all changes
        session.commit()
        
        print(f"\n✅ Successfully created {len(created_customers)} test customers!")
        print("\n📋 Summary of created customers:")
        print("-" * 60)
        
        for item in created_customers:
            customer = item["customer"]
            print(f"👤 {customer.full_name:<20} | 📞 {customer.primary_phone} | 📅 {item['date']}")
        
        print(f"\n🎯 Test Instructions:")
        print("1. Open your dashboard: http://localhost:8000")
        print("2. Test these date filters:")
        print("   - Today: Should show 'Today Customer 1' and 'Today Customer 2'")
        print("   - Yesterday: Should show 'Yesterday Customer 1', 'Yesterday Customer 2', and 'Yesterday Customer 3'")
        print("   - This Week: Should show recent customers")
        print("   - All: Should show all customers including past and future")
        print("3. Check if date badges show correctly:")
        print("   - 'Today' for today's customers")
        print("   - 'Yesterday' for yesterday's customers (should show 3 customers)")
        print("   - 'X days ago' for past customers")
        print("   - 'Future' for future customers")
        
    except Exception as e:
        session.rollback()
        print(f"❌ Error creating test data: {e}")
        raise
    finally:
        session.close()

def clean_test_data():
    """Remove test customers (phones starting with +918888888)"""
    session = get_session()
    
    try:
        print("🧹 Cleaning up test data...")
        
        # Find and delete test customers
        test_customers = session.query(Customer).filter(
            Customer.primary_phone.like('+918888888%')
        ).all()
        
        print(f"Found {len(test_customers)} test customers to delete")
        
        for customer in test_customers:
            # Delete associated loans first
            loans = session.query(Loan).filter(Loan.customer_id == customer.id).all()
            for loan in loans:
                session.delete(loan)
            
            # Delete customer
            session.delete(customer)
            print(f"🗑️  Deleted: {customer.full_name} ({customer.primary_phone})")
        
        session.commit()
        print("✅ Test data cleanup completed!")
        
    except Exception as e:
        session.rollback()
        print(f"❌ Error cleaning test data: {e}")
        raise
    finally:
        session.close()

def main():
    """Main function"""
    print("🧪 Test Date Data Script")
    print("=" * 40)
    print("This script creates test customers with various dates to test filtering")
    print()
    
    action = input("Choose action:\n1. Create test data\n2. Clean test data\n3. Exit\nEnter choice (1-3): ").strip()
    
    if action == "1":
        create_test_customers()
    elif action == "2":
        clean_test_data()
    elif action == "3":
        print("👋 Goodbye!")
        return
    else:
        print("❌ Invalid choice!")
        return

if __name__ == "__main__":
    main()
