#!/usr/bin/env python3
"""
Database Schema Visualization
Shows the relationships between all tables in the voice assistant application
"""
import os
import sys
from pathlib import Path

# Add current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from database.schemas import get_session, Customer, Loan, FileUpload, UploadRow, CallSession, CallStatusUpdate
from sqlalchemy import inspect

def analyze_table_relationships():
    """Analyze and display table relationships"""
    
    print("🗄️  DATABASE SCHEMA ANALYSIS")
    print("=" * 60)
    
    session = get_session()
    inspector = inspect(session.bind)
    
    # Get all table names
    tables = inspector.get_table_names()
    print(f"📊 Total Tables: {len(tables)}")
    print(f"📋 Tables: {', '.join(tables)}")
    print()
    
    # Analyze each table
    for table_name in tables:
        print(f"🔍 TABLE: {table_name}")
        print("-" * 40)
        
        # Get columns
        columns = inspector.get_columns(table_name)
        print(f"📝 Columns ({len(columns)}):")
        for col in columns:
            col_type = str(col['type'])
            nullable = "NULL" if col['nullable'] else "NOT NULL"
            default = f" DEFAULT({col['default']})" if col['default'] else ""
            print(f"   • {col['name']:<25} {col_type:<20} {nullable}{default}")
        
        # Get foreign keys
        foreign_keys = inspector.get_foreign_keys(table_name)
        if foreign_keys:
            print(f"\n🔗 Foreign Keys ({len(foreign_keys)}):")
            for fk in foreign_keys:
                print(f"   • {fk['constrained_columns'][0]} → {fk['referred_table']}.{fk['referred_columns'][0]}")
        
        # Get indexes
        indexes = inspector.get_indexes(table_name)
        if indexes:
            print(f"\n📇 Indexes ({len(indexes)}):")
            for idx in indexes:
                unique = "UNIQUE " if idx['unique'] else ""
                print(f"   • {unique}{idx['name']}: {', '.join(idx['column_names'])}")
        
        print("\n" + "=" * 60 + "\n")
    
    session.close()

def show_data_flow_example():
    """Show a real example of data flowing through tables"""
    
    print("🎯 DATA FLOW EXAMPLE")
    print("=" * 60)
    
    session = get_session()
    
    try:
        # Check if we have any data
        customer_count = session.query(Customer).count()
        loan_count = session.query(Loan).count()
        upload_count = session.query(FileUpload).count()
        call_count = session.query(CallSession).count()
        
        print(f"📊 Current Data Counts:")
        print(f"   👥 Customers: {customer_count}")
        print(f"   💰 Loans: {loan_count}")
        print(f"   📁 File Uploads: {upload_count}")
        print(f"   📞 Call Sessions: {call_count}")
        print()
        
        if customer_count > 0:
            print("🔍 SAMPLE DATA RELATIONSHIPS:")
            print("-" * 40)
            
            # Get a sample customer with all related data
            customer = session.query(Customer).first()
            print(f"👤 Sample Customer: {customer.full_name}")
            print(f"   📞 Phone: {customer.primary_phone}")
            print(f"   🆔 ID: {customer.id}")
            print(f"   📅 First Uploaded: {customer.first_uploaded_at}")
            print()
            
            # Show their loans
            loans = customer.loans
            print(f"💰 Customer's Loans ({len(loans)}):")
            for loan in loans:
                print(f"   • Loan {loan.loan_id}: ₹{loan.outstanding_amount}")
                print(f"     Branch: {loan.branch}")
                print(f"     Employee: {loan.employee_name}")
            print()
            
            # Show call sessions
            call_sessions = customer.call_sessions
            print(f"📞 Customer's Call Sessions ({len(call_sessions)}):")
            for call in call_sessions:
                print(f"   • Call {call.call_sid}: {call.status}")
                print(f"     Initiated: {call.initiated_at}")
                print(f"     Duration: {call.duration_seconds}s" if call.duration_seconds else "     Duration: Ongoing")
            print()
            
        else:
            print("ℹ️  No data found. Upload some CSV files to see data flow!")
    
    except Exception as e:
        print(f"❌ Error analyzing data: {e}")
    finally:
        session.close()

def show_table_purposes():
    """Explain the purpose of each table"""
    
    print("📋 TABLE PURPOSES & USAGE")
    print("=" * 60)
    
    table_info = {
        "customers": {
            "purpose": "Root entity storing customer personal information",
            "key_fields": ["full_name", "primary_phone", "state", "fingerprint"],
            "relationships": "One-to-many with loans and call_sessions",
            "usage": "Deduplication, contact info, customer management"
        },
        "loans": {
            "purpose": "Financial product information linked to customers",
            "key_fields": ["loan_id", "outstanding_amount", "due_amount", "customer_id"],
            "relationships": "Many-to-one with customers, one-to-many with call_sessions",
            "usage": "Loan details, payment tracking, branch assignment"
        },
        "file_uploads": {
            "purpose": "Track CSV batch uploads for audit and processing",
            "key_fields": ["filename", "total_records", "status", "uploaded_at"],
            "relationships": "One-to-many with upload_rows and call_sessions",
            "usage": "Batch processing, error tracking, upload history"
        },
        "upload_rows": {
            "purpose": "Individual CSV rows with processing status and matching",
            "key_fields": ["raw_data", "match_customer_id", "match_loan_id", "status"],
            "relationships": "Many-to-one with file_uploads, customers, loans",
            "usage": "Row-level processing, deduplication, error handling"
        },
        "call_sessions": {
            "purpose": "Individual call tracking with Exotel integration",
            "key_fields": ["call_sid", "customer_id", "loan_id", "status"],
            "relationships": "Many-to-one with customers, loans, file_uploads",
            "usage": "Call lifecycle, duration tracking, status updates"
        },
        "call_status_updates": {
            "purpose": "Detailed call status history for timeline tracking",
            "key_fields": ["call_session_id", "status", "timestamp", "message"],
            "relationships": "Many-to-one with call_sessions",
            "usage": "Call timeline, debugging, status history"
        }
    }
    
    for table_name, info in table_info.items():
        print(f"🔍 {table_name.upper()}")
        print(f"   Purpose: {info['purpose']}")
        print(f"   Key Fields: {', '.join(info['key_fields'])}")
        print(f"   Relationships: {info['relationships']}")
        print(f"   Usage: {info['usage']}")
        print()

def main():
    """Main function"""
    print("🗄️  VOICE ASSISTANT DATABASE ANALYSIS")
    print("=" * 70)
    print("This script analyzes the database schema and shows data relationships")
    print()
    
    choice = input("Choose analysis:\n1. Table Structure\n2. Data Flow Example\n3. Table Purposes\n4. All\nEnter choice (1-4): ").strip()
    
    if choice == "1":
        analyze_table_relationships()
    elif choice == "2":
        show_data_flow_example()
    elif choice == "3":
        show_table_purposes()
    elif choice == "4":
        show_table_purposes()
        print("\n")
        show_data_flow_example()
        print("\n")
        analyze_table_relationships()
    else:
        print("❌ Invalid choice!")

if __name__ == "__main__":
    main()
