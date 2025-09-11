#!/usr/bin/env python3
"""
Upload Entries Schema - Separate entry for each customer upload
Each customer upload instance is stored as a separate record with timestamp
"""
import os
import uuid
from datetime import datetime
from typing import Optional, List
from decimal import Decimal
from sqlalchemy import (
    create_engine, Column, String, Text, Integer, 
    Numeric, Date, DateTime, Boolean, JSON, UUID, ForeignKey,
    UniqueConstraint, Index, func, text
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from dotenv import load_dotenv

load_dotenv()

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL, echo=False)
Base = declarative_base()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class CustomerUploadEntry(Base):
    """
    Individual customer upload entry - one record per customer per upload
    This allows the same customer to appear multiple times across different dates
    """
    __tablename__ = "customer_upload_entries"
    
    # Primary key
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Upload batch information
    file_upload_id = Column(PG_UUID(as_uuid=True), ForeignKey('file_uploads.id'), nullable=False)
    upload_timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # Customer information (duplicated for each upload entry)
    customer_fingerprint = Column(String(64), nullable=False)  # For deduplication reference
    full_name = Column(String(255), nullable=False)
    primary_phone = Column(String(20), nullable=False)
    state = Column(String(100))
    email = Column(String(255))
    
    # Loan information for this specific upload
    loan_id = Column(String(100), nullable=False)
    principal_amount = Column(Numeric(15, 2))
    outstanding_amount = Column(Numeric(15, 2))
    due_amount = Column(Numeric(15, 2))
    next_due_date = Column(Date)
    last_paid_date = Column(Date)
    last_paid_amount = Column(Numeric(15, 2))
    
    # Branch and employee information
    cluster = Column(String(100))
    branch = Column(String(255))
    branch_contact_number = Column(String(20))
    employee_name = Column(String(255))
    employee_id = Column(String(50))
    employee_contact_number = Column(String(20))
    
    # Status and metadata
    processing_status = Column(String(50), default='processed')  # processed, error, duplicate
    is_new_customer = Column(Boolean, default=True)  # Whether this was a new customer in the system
    is_new_loan = Column(Boolean, default=True)  # Whether this was a new loan for the customer
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    file_upload = relationship("FileUpload", back_populates="upload_entries")
    
    # Indexes for efficient querying
    __table_args__ = (
        Index('idx_upload_entries_timestamp', 'upload_timestamp'),
        Index('idx_upload_entries_phone', 'primary_phone'),
        Index('idx_upload_entries_fingerprint', 'customer_fingerprint'),
        Index('idx_upload_entries_file_upload', 'file_upload_id'),
        Index('idx_upload_entries_loan_id', 'loan_id'),
    )

# Update FileUpload model to include relationship with upload entries
class FileUpload(Base):
    """File upload tracking with relationship to individual entries"""
    __tablename__ = "file_uploads"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    uploaded_by = Column(String(100))
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    
    # Processing statistics
    total_records = Column(Integer, default=0)
    processed_records = Column(Integer, default=0)
    success_records = Column(Integer, default=0)
    failed_records = Column(Integer, default=0)
    duplicate_records = Column(Integer, default=0)
    
    # Status
    status = Column(String(50), default='pending')
    processing_logs = Column(JSON)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    upload_entries = relationship("CustomerUploadEntry", back_populates="file_upload")

def get_session():
    """Get database session"""
    return SessionLocal()

def create_tables():
    """Create all tables if they don't exist"""
    try:
        Base.metadata.create_all(bind=engine, checkfirst=True)
        print("✅ Upload entries tables created successfully!")
    except Exception as e:
        print(f"ℹ️  Tables may already exist: {e}")
        print("✅ Continuing with existing schema...")

def migrate_existing_data():
    """Migrate existing customer/loan data to upload entries format"""
    print("🔄 Migrating existing data to upload entries format...")
    
    session = get_session()
    try:
        # Import existing models
        from database.schemas import Customer, Loan, FileUpload as OldFileUpload
        
        # Get all customers with their loans
        customers = session.query(Customer).all()
        
        for customer in customers:
            # For each customer, create upload entries based on their loans
            for loan in customer.loans:
                # Create an upload entry for each loan
                upload_entry = CustomerUploadEntry(
                    # We'll need to associate with a file upload - create a default one if needed
                    file_upload_id=None,  # Will be updated
                    upload_timestamp=customer.first_uploaded_at or customer.created_at,
                    
                    # Customer data
                    customer_fingerprint=customer.fingerprint,
                    full_name=customer.full_name,
                    primary_phone=customer.primary_phone,
                    state=customer.state,
                    email=customer.email,
                    
                    # Loan data
                    loan_id=loan.loan_id,
                    principal_amount=loan.principal_amount,
                    outstanding_amount=loan.outstanding_amount,
                    due_amount=loan.due_amount,
                    next_due_date=loan.next_due_date,
                    last_paid_date=loan.last_paid_date,
                    last_paid_amount=loan.last_paid_amount,
                    
                    # Branch data
                    cluster=loan.cluster,
                    branch=loan.branch,
                    branch_contact_number=loan.branch_contact_number,
                    employee_name=loan.employee_name,
                    employee_id=loan.employee_id,
                    employee_contact_number=loan.employee_contact_number,
                    
                    # Metadata
                    is_new_customer=False,  # Existing data
                    is_new_loan=False,
                    processing_status='migrated'
                )
                
                session.add(upload_entry)
        
        session.commit()
        print(f"✅ Migrated {len(customers)} customers to upload entries format")
        
    except Exception as e:
        session.rollback()
        print(f"❌ Migration failed: {e}")
        raise
    finally:
        session.close()

if __name__ == "__main__":
    print("🚀 Creating Upload Entries Schema")
    create_tables()
