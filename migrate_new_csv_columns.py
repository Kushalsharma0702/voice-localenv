#!/usr/bin/env python3
"""
Database migration script to add new CSV columns to existing tables
Adds support for: state, Cluster, Branch, Branch Contact Number, Employee, 
Employee ID, Employee Contact Number, Last Paid Date, Last Paid Amount, Due Amount
"""
import os
import sys
from sqlalchemy import text
from dotenv import load_dotenv

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Load environment variables
load_dotenv()

from database.schemas import engine

def migrate_new_csv_columns():
    """Add new columns to support enhanced CSV format"""
    
    print("🔄 Starting migration for new CSV columns...")
    print("=" * 50)
    
    with engine.connect() as connection:
        try:
            # Start transaction
            with connection.begin():
                
                # 1. Add state column to customers table
                print("📋 Adding 'state' column to customers table...")
                try:
                    connection.execute(text("""
                        ALTER TABLE customers 
                        ADD COLUMN state VARCHAR(100)
                    """))
                    print("✅ Added state column to customers")
                except Exception as e:
                    if "already exists" in str(e) or "duplicate column" in str(e).lower():
                        print("⚠️  state column already exists in customers")
                    else:
                        print(f"❌ Error adding state column to customers: {e}")
                        raise
                
                # 2. Add new columns to loans table
                new_loan_columns = [
                    ("due_amount", "NUMERIC(15, 2)", "Current due amount"),
                    ("last_paid_date", "DATE", "Last payment date"),
                    ("last_paid_amount", "NUMERIC(15, 2)", "Last payment amount"),
                    ("cluster", "VARCHAR(100)", "Cluster information"),
                    ("branch", "VARCHAR(255)", "Branch name"),
                    ("branch_contact_number", "VARCHAR(20)", "Branch contact number"),
                    ("employee_name", "VARCHAR(255)", "Employee name"),
                    ("employee_id", "VARCHAR(100)", "Employee ID"),
                    ("employee_contact_number", "VARCHAR(20)", "Employee contact number")
                ]
                
                for column_name, column_type, description in new_loan_columns:
                    print(f"📋 Adding '{column_name}' column to loans table ({description})...")
                    try:
                        connection.execute(text(f"""
                            ALTER TABLE loans 
                            ADD COLUMN {column_name} {column_type}
                        """))
                        print(f"✅ Added {column_name} column to loans")
                    except Exception as e:
                        if "already exists" in str(e) or "duplicate column" in str(e).lower():
                            print(f"⚠️  {column_name} column already exists in loans")
                        else:
                            print(f"❌ Error adding {column_name} column to loans: {e}")
                            raise
                
                # 3. Create new indexes for better performance
                print("📋 Creating new indexes...")
                new_indexes = [
                    ("ix_customer_state", "customers", "state"),
                    ("ix_loan_cluster", "loans", "cluster"),
                    ("ix_loan_branch", "loans", "branch"),
                    ("ix_loan_employee_id", "loans", "employee_id"),
                    ("ix_loan_last_paid_date", "loans", "last_paid_date"),
                    ("ix_loan_due_amount", "loans", "due_amount")
                ]
                
                for index_name, table_name, column_name in new_indexes:
                    try:
                        connection.execute(text(f"""
                            CREATE INDEX IF NOT EXISTS {index_name} ON {table_name}({column_name})
                        """))
                        print(f"✅ Created index {index_name}")
                    except Exception as e:
                        if "already exists" in str(e):
                            print(f"⚠️  Index {index_name} already exists")
                        else:
                            print(f"❌ Error creating index {index_name}: {e}")
                            raise
                
                print("\n🎉 Migration completed successfully!")
                print("=" * 50)
                print("New CSV columns added:")
                print("📞 Customer Table:")
                print("  • state - Customer's state/region")
                print("\n🏦 Loan Table:")
                print("  • due_amount - Current amount due")
                print("  • last_paid_date - Date of last payment")
                print("  • last_paid_amount - Amount of last payment")
                print("  • cluster - Business cluster")
                print("  • branch - Branch name")
                print("  • branch_contact_number - Branch phone")
                print("  • employee_name - Assigned employee")
                print("  • employee_id - Employee identifier")
                print("  • employee_contact_number - Employee phone")
                
        except Exception as e:
            print(f"❌ Migration failed: {e}")
            raise

def verify_migration():
    """Verify that all new columns were added successfully"""
    print("\n🔍 Verifying migration...")
    
    with engine.connect() as connection:
        try:
            # Check customers table structure
            result = connection.execute(text("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'customers' 
                AND column_name IN ('state')
                ORDER BY column_name
            """))
            customer_columns = result.fetchall()
            
            # Check loans table structure
            result = connection.execute(text("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'loans' 
                AND column_name IN ('due_amount', 'last_paid_date', 'last_paid_amount', 
                                   'cluster', 'branch', 'branch_contact_number',
                                   'employee_name', 'employee_id', 'employee_contact_number')
                ORDER BY column_name
            """))
            loan_columns = result.fetchall()
            
            print(f"✅ Found {len(customer_columns)} new columns in customers table")
            for col in customer_columns:
                print(f"   • {col[0]} ({col[1]})")
            
            print(f"✅ Found {len(loan_columns)} new columns in loans table")
            for col in loan_columns:
                print(f"   • {col[0]} ({col[1]})")
            
            if len(customer_columns) >= 1 and len(loan_columns) >= 9:
                print("\n🎉 Migration verification successful!")
                return True
            else:
                print("\n❌ Migration verification failed - some columns missing")
                return False
                
        except Exception as e:
            print(f"❌ Verification failed: {e}")
            return False

def main():
    """Main migration function"""
    print("🚀 New CSV Columns Migration Script")
    print("=" * 50)
    print("This script will add support for the new CSV format with columns:")
    print("name, phone, loan_id, amount, due_date, state, Cluster, Branch,")
    print("Branch Contact Number, Employee, Employee ID, Employee Contact Number,")
    print("Last Paid Date, Last Paid Amount, Due Amount")
    print("=" * 50)
    
    try:
        migrate_new_csv_columns()
        
        if verify_migration():
            print("\n✅ Migration completed and verified successfully!")
            print("You can now upload CSV files with the new format.")
        else:
            print("\n❌ Migration completed but verification failed.")
            sys.exit(1)
            
    except Exception as e:
        print(f"💥 Critical error during migration: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
