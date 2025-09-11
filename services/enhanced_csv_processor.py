#!/usr/bin/env python3
"""
Enhanced Banking CSV Processing Service
Handles the new CSV format with advanced filtering and deduplication:
name,phone,loan_id,amount,due_date,state,Cluster,Branch,Branch Contact Number,Employee,Employee ID,Employee Contact Number,Last Paid Date,Last Paid Amount,Due Amount
"""

import os
import pandas as pd
import hashlib
from datetime import datetime, date
from typing import Dict, List, Any, Optional, Tuple
from decimal import Decimal
import re
import logging
from dataclasses import dataclass
from enum import Enum

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ProcessingStatus(Enum):
    PENDING = "pending"
    MATCHED = "matched" 
    CREATED = "created"
    ERROR = "error"
    DUPLICATE = "duplicate"

class MatchMethod(Enum):
    EXACT_MATCH = "exact_match"
    FUZZY_MATCH = "fuzzy_match"
    CREATED_NEW = "created_new"

@dataclass
class CSVRow:
    """Represents a single CSV row with parsed data"""
    line_number: int
    raw_data: Dict[str, Any]
    
    # Parsed fields
    customer_name: str
    phone_normalized: str
    loan_id_text: str
    amount: Optional[Decimal]
    due_date: Optional[date]
    state: str
    cluster: str
    branch: str
    branch_contact_number: str
    employee_name: str
    employee_id: str
    employee_contact: str
    last_paid_date: Optional[date]
    last_paid_amount: Optional[Decimal]
    due_amount: Optional[Decimal]
    
    # Processing results
    record_fingerprint: str
    status: ProcessingStatus = ProcessingStatus.PENDING
    error_message: Optional[str] = None
    matched_customer_id: Optional[str] = None
    matched_loan_id: Optional[str] = None
    match_method: Optional[MatchMethod] = None

class EnhancedCSVProcessor:
    """Enhanced CSV processor with advanced deduplication and filtering"""
    
    def __init__(self, database_session):
        self.session = database_session
        self.processing_stats = {
            'total_records': 0,
            'processed_records': 0,
            'new_customers': 0,
            'updated_customers': 0,
            'new_loans': 0,
            'updated_loans': 0,
            'duplicate_records': 0,
            'error_records': 0
        }
        
    def normalize_phone(self, phone: str) -> str:
        """Normalize phone number for consistent storage"""
        if not phone:
            return ""
        
        # Remove all non-digit characters
        digits_only = re.sub(r'\D', '', str(phone))
        
        # Handle Indian phone numbers
        if len(digits_only) == 10:
            return f"+91{digits_only}"
        elif len(digits_only) == 12 and digits_only.startswith("91"):
            return f"+{digits_only}"
        elif len(digits_only) == 13 and digits_only.startswith("91"):
            return f"+{digits_only}"
        
        return digits_only
    
    def parse_date(self, date_str: str) -> Optional[date]:
        """Parse date from various formats"""
        if pd.isna(date_str) or not date_str:
            return None
        
        date_formats = [
            '%Y-%m-%d',
            '%d-%m-%Y',
            '%d/%m/%Y',
            '%m/%d/%Y',
            '%d-%b-%Y',
            '%d-%B-%Y'
        ]
        
        for fmt in date_formats:
            try:
                return datetime.strptime(str(date_str), fmt).date()
            except ValueError:
                continue
        
        logger.warning(f"Could not parse date: {date_str}")
        return None
    
    def parse_decimal(self, value: str) -> Optional[Decimal]:
        """Parse decimal value from string"""
        if pd.isna(value) or not value:
            return None
        
        try:
            # Remove currency symbols and commas
            clean_value = re.sub(r'[₹,$\s]', '', str(value))
            return Decimal(clean_value)
        except Exception as e:
            logger.warning(f"Could not parse decimal: {value} - {e}")
            return None
    
    def compute_record_fingerprint(self, phone: str, loan_id: str, name: str) -> str:
        """Create deterministic fingerprint for deduplication"""
        phone_norm = self.normalize_phone(phone)
        loan_norm = (loan_id or "").strip()
        name_norm = (name or "").strip().lower()
        content = f"{phone_norm}|{loan_norm}|{name_norm}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
    
    def compute_customer_fingerprint(self, name: str, phone: str) -> str:
        """Create customer fingerprint for deduplication"""
        name_norm = (name or "").strip().lower()
        phone_norm = self.normalize_phone(phone)
        content = f"{name_norm}|{phone_norm}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
    
    def parse_csv_row(self, row_data: Dict[str, Any], line_number: int) -> CSVRow:
        """Parse a single CSV row into structured data"""
        try:
            # Extract and normalize data
            customer_name = str(row_data.get('name', '')).strip()
            phone_raw = str(row_data.get('phone', ''))
            phone_normalized = self.normalize_phone(phone_raw)
            loan_id_text = str(row_data.get('loan_id', '')).strip()
            
            # Parse financial data
            amount = self.parse_decimal(row_data.get('amount'))
            due_date = self.parse_date(row_data.get('due_date'))
            last_paid_date = self.parse_date(row_data.get('Last Paid Date'))
            last_paid_amount = self.parse_decimal(row_data.get('Last Paid Amount'))
            due_amount = self.parse_decimal(row_data.get('Due Amount'))
            
            # Extract organizational data
            state = str(row_data.get('state', '')).strip()
            cluster = str(row_data.get('Cluster', '')).strip()
            branch = str(row_data.get('Branch', '')).strip()
            branch_contact = str(row_data.get('Branch Contact Number', '')).strip()
            employee_name = str(row_data.get('Employee', '')).strip()
            employee_id = str(row_data.get('Employee ID', '')).strip()
            employee_contact = str(row_data.get('Employee Contact Number', '')).strip()
            
            # Create fingerprint for deduplication
            record_fingerprint = self.compute_record_fingerprint(
                phone_normalized, loan_id_text, customer_name
            )
            
            return CSVRow(
                line_number=line_number,
                raw_data=row_data,
                customer_name=customer_name,
                phone_normalized=phone_normalized,
                loan_id_text=loan_id_text,
                amount=amount,
                due_date=due_date,
                state=state,
                cluster=cluster,
                branch=branch,
                branch_contact_number=branch_contact,
                employee_name=employee_name,
                employee_id=employee_id,
                employee_contact=employee_contact,
                last_paid_date=last_paid_date,
                last_paid_amount=last_paid_amount,
                due_amount=due_amount,
                record_fingerprint=record_fingerprint
            )
            
        except Exception as e:
            logger.error(f"Error parsing row {line_number}: {e}")
            record_fingerprint = self.compute_record_fingerprint("", "", "")
            return CSVRow(
                line_number=line_number,
                raw_data=row_data,
                customer_name="",
                phone_normalized="",
                loan_id_text="",
                amount=None,
                due_date=None,
                state="",
                cluster="",
                branch="",
                branch_contact_number="",
                employee_name="",
                employee_id="",
                employee_contact="",
                last_paid_date=None,
                last_paid_amount=None,
                due_amount=None,
                record_fingerprint=record_fingerprint,
                status=ProcessingStatus.ERROR,
                error_message=str(e)
            )
    
    def find_existing_customer(self, csv_row: CSVRow) -> Tuple[Optional[Any], MatchMethod]:
        """Find existing customer using various matching strategies"""
        from database.schemas import Customer
        
        # Strategy 1: Exact phone match
        if csv_row.phone_normalized:
            customer = self.session.query(Customer).filter(
                Customer.primary_phone == csv_row.phone_normalized
            ).first()
            
            if customer:
                return customer, MatchMethod.EXACT_MATCH
        
        # Strategy 2: Name + partial phone match (fuzzy matching)
        if csv_row.customer_name and len(csv_row.customer_name) > 3:
            customers = self.session.query(Customer).filter(
                Customer.full_name.ilike(f"%{csv_row.customer_name}%")
            ).all()
            
            for customer in customers:
                # Check if phone numbers are similar (last 4 digits)
                if (customer.primary_phone and csv_row.phone_normalized and
                    customer.primary_phone[-4:] == csv_row.phone_normalized[-4:]):
                    return customer, MatchMethod.FUZZY_MATCH
        
        return None, MatchMethod.CREATED_NEW
    
    def find_existing_loan(self, customer_id: str, loan_id: str) -> Optional[Any]:
        """Find existing loan by loan ID (globally unique)"""
        from database.schemas import Loan
        
        # Since loan_id is globally unique, we only need to search by loan_id
        return self.session.query(Loan).filter(
            Loan.loan_id == loan_id
        ).first()
    
    def create_or_update_customer(self, csv_row: CSVRow) -> Tuple[Any, bool]:
        """Create new customer or update existing one"""
        from database.schemas import Customer
        
        # Find existing customer
        existing_customer, match_method = self.find_existing_customer(csv_row)
        
        if existing_customer:
            # Update existing customer (only customer-specific fields, but preserve first_uploaded_at)
            existing_customer.state = csv_row.state or existing_customer.state
            existing_customer.updated_at = datetime.utcnow()
            # DO NOT update first_uploaded_at - it should preserve the original upload date
            
            csv_row.matched_customer_id = str(existing_customer.id)
            csv_row.match_method = match_method
            
            return existing_customer, False  # Not new
        
        else:
            # Create new customer
            customer_fingerprint = self.compute_customer_fingerprint(
                csv_row.customer_name, csv_row.phone_normalized
            )
            
            new_customer = Customer(
                fingerprint=customer_fingerprint,
                full_name=csv_row.customer_name,
                primary_phone=csv_row.phone_normalized,
                state=csv_row.state,
                first_uploaded_at=datetime.utcnow()
            )
            
            self.session.add(new_customer)
            self.session.flush()  # Get the ID
            
            csv_row.matched_customer_id = str(new_customer.id)
            csv_row.match_method = MatchMethod.CREATED_NEW
            
            return new_customer, True  # Is new
    
    def create_or_update_loan(self, customer: Any, csv_row: CSVRow) -> Tuple[Any, bool]:
        """Create new loan or update existing one"""
        from database.schemas import Loan
        
        # Find existing loan
        existing_loan = self.find_existing_loan(customer.id, csv_row.loan_id_text)
        
        if existing_loan:
            # Update existing loan
            existing_loan.outstanding_amount = csv_row.amount or existing_loan.outstanding_amount
            existing_loan.due_amount = csv_row.due_amount or existing_loan.due_amount
            existing_loan.next_due_date = csv_row.due_date or existing_loan.next_due_date
            existing_loan.last_paid_date = csv_row.last_paid_date or existing_loan.last_paid_date
            existing_loan.last_paid_amount = csv_row.last_paid_amount or existing_loan.last_paid_amount
            existing_loan.cluster = csv_row.cluster or existing_loan.cluster
            existing_loan.branch = csv_row.branch or existing_loan.branch
            existing_loan.branch_contact_number = csv_row.branch_contact_number or existing_loan.branch_contact_number
            existing_loan.employee_name = csv_row.employee_name or existing_loan.employee_name
            existing_loan.employee_id = csv_row.employee_id or existing_loan.employee_id
            existing_loan.employee_contact_number = csv_row.employee_contact or existing_loan.employee_contact_number
            existing_loan.updated_at = datetime.utcnow()
            
            csv_row.matched_loan_id = str(existing_loan.id)
            
            return existing_loan, False  # Not new
        
        else:
            # Create new loan
            new_loan = Loan(
                customer_id=customer.id,
                loan_id=csv_row.loan_id_text,
                outstanding_amount=csv_row.amount,
                due_amount=csv_row.due_amount,
                next_due_date=csv_row.due_date,
                last_paid_date=csv_row.last_paid_date,
                last_paid_amount=csv_row.last_paid_amount,
                status='active',
                # Add cluster/branch/employee data
                cluster=csv_row.cluster,
                branch=csv_row.branch,
                branch_contact_number=csv_row.branch_contact_number,
                employee_name=csv_row.employee_name,
                employee_id=csv_row.employee_id,
                employee_contact_number=csv_row.employee_contact
            )
            
            self.session.add(new_loan)
            self.session.flush()  # Get the ID
            
            csv_row.matched_loan_id = str(new_loan.id)
            
            return new_loan, True  # Is new
    
    def process_csv_file(self, file_path: str, upload_id: str) -> Dict[str, Any]:
        """Process entire CSV file with enhanced deduplication"""
        try:
            # Read CSV file
            df = pd.read_csv(file_path)
            
            # Expected columns for the new format
            expected_columns = [
                'name', 'phone', 'loan_id', 'amount', 'due_date', 'state',
                'Cluster', 'Branch', 'Branch Contact Number', 'Employee',
                'Employee ID', 'Employee Contact Number', 'Last Paid Date',
                'Last Paid Amount', 'Due Amount'
            ]
            
            # Validate columns
            missing_columns = set(expected_columns) - set(df.columns)
            if missing_columns:
                logger.warning(f"Missing columns: {missing_columns}")
            
            self.processing_stats['total_records'] = len(df)
            
            # Process each row
            processed_rows = []
            duplicate_fingerprints = set()
            
            for index, row in df.iterrows():
                try:
                    # Parse row
                    csv_row = self.parse_csv_row(row.to_dict(), index + 1)
                    
                    # Check for duplicates within this file
                    if csv_row.record_fingerprint in duplicate_fingerprints:
                        csv_row.status = ProcessingStatus.DUPLICATE
                        csv_row.error_message = "Duplicate record within file"
                        self.processing_stats['duplicate_records'] += 1
                        processed_rows.append(csv_row)
                        continue
                    
                    duplicate_fingerprints.add(csv_row.record_fingerprint)
                    
                    # Validate required fields
                    if not csv_row.customer_name or not csv_row.loan_id_text:
                        csv_row.status = ProcessingStatus.ERROR
                        csv_row.error_message = "Missing required fields (name or loan_id)"
                        self.processing_stats['error_records'] += 1
                        processed_rows.append(csv_row)
                        continue
                    
                    # Process customer
                    customer, is_new_customer = self.create_or_update_customer(csv_row)
                    if is_new_customer:
                        self.processing_stats['new_customers'] += 1
                    else:
                        self.processing_stats['updated_customers'] += 1
                    
                    # Process loan
                    loan, is_new_loan = self.create_or_update_loan(customer, csv_row)
                    if is_new_loan:
                        self.processing_stats['new_loans'] += 1
                    else:
                        self.processing_stats['updated_loans'] += 1
                    
                    # Save upload record
                    self.save_upload_record(upload_id, csv_row)
                    
                    csv_row.status = ProcessingStatus.MATCHED
                    self.processing_stats['processed_records'] += 1
                    
                except Exception as e:
                    logger.error(f"Error processing row {index + 1}: {e}")
                    csv_row.status = ProcessingStatus.ERROR
                    csv_row.error_message = str(e)
                    self.processing_stats['error_records'] += 1
                
                processed_rows.append(csv_row)
            
            # Commit all changes
            self.session.commit()
            
            logger.info(f"Processing completed: {self.processing_stats}")
            
            return {
                'success': True,
                'stats': self.processing_stats,
                'processed_rows': len(processed_rows),
                'errors': [row for row in processed_rows if row.status == ProcessingStatus.ERROR]
            }
            
        except Exception as e:
            logger.error(f"Error processing CSV file: {e}")
            self.session.rollback()
            return {
                'success': False,
                'error': str(e),
                'stats': self.processing_stats
            }
    
    def save_upload_record(self, upload_id: str, csv_row: CSVRow):
        """Save upload record to database"""
        from database.schemas import UploadRow
        
        upload_record = UploadRow(
            file_upload_id=upload_id,
            line_number=csv_row.line_number,
            raw_data=csv_row.raw_data,
            row_fingerprint=csv_row.record_fingerprint,
            phone_normalized=csv_row.phone_normalized,
            loan_id_text=csv_row.loan_id_text,
            match_customer_id=csv_row.matched_customer_id,
            match_loan_id=csv_row.matched_loan_id,
            match_method=csv_row.match_method.value if csv_row.match_method else None,
            status=csv_row.status.value,
            error=csv_row.error_message,  # Fixed: use 'error' instead of 'error_message'
            matched_at=datetime.utcnow() if csv_row.status == ProcessingStatus.MATCHED else None
        )
        
        self.session.add(upload_record)

def create_sample_csv():
    """Create a sample CSV file with the new format"""
    sample_data = [
        {
            'name': 'Rajesh Kumar',
            'phone': '9876543210',
            'loan_id': 'LOAN001234',
            'amount': '50000.00',
            'due_date': '2024-12-15',
            'state': 'Karnataka',
            'Cluster': 'Bangalore',
            'Branch': 'Koramangala',
            'Branch Contact Number': '080-12345678',
            'Employee': 'Priya Sharma',
            'Employee ID': 'EMP001',
            'Employee Contact Number': '9876543200',
            'Last Paid Date': '2024-11-15',
            'Last Paid Amount': '3000.00',
            'Due Amount': '5000.00'
        },
        {
            'name': 'Priya Patel',
            'phone': '9876543211',
            'loan_id': 'LOAN001235',
            'amount': '75000.00',
            'due_date': '2024-12-20',
            'state': 'Gujarat',
            'Cluster': 'Ahmedabad',
            'Branch': 'Satellite',
            'Branch Contact Number': '079-12345678',
            'Employee': 'Rahul Verma',
            'Employee ID': 'EMP002',
            'Employee Contact Number': '9876543201',
            'Last Paid Date': '2024-10-20',
            'Last Paid Amount': '4500.00',
            'Due Amount': '7500.00'
        },
        {
            'name': 'Amit Singh',
            'phone': '9876543212',
            'loan_id': 'LOAN001236',
            'amount': '100000.00',
            'due_date': '2024-12-10',
            'state': 'Maharashtra',
            'Cluster': 'Mumbai',
            'Branch': 'Andheri',
            'Branch Contact Number': '022-12345678',
            'Employee': 'Sneha Gupta',
            'Employee ID': 'EMP003',
            'Employee Contact Number': '9876543202',
            'Last Paid Date': '2024-09-10',
            'Last Paid Amount': '6000.00',
            'Due Amount': '10000.00'
        }
    ]
    
    df = pd.DataFrame(sample_data)
    df.to_csv('sample_banking_data_new_format.csv', index=False)
    print("✅ Sample CSV file created: sample_banking_data_new_format.csv")

if __name__ == "__main__":
    # Create sample CSV for testing
    create_sample_csv()
    print("📋 Enhanced CSV processor ready!")
    print("\nSupported CSV format:")
    print("name,phone,loan_id,amount,due_date,state,Cluster,Branch,Branch Contact Number,Employee,Employee ID,Employee Contact Number,Last Paid Date,Last Paid Amount,Due Amount")
