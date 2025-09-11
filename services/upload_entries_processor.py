#!/usr/bin/env python3
"""
Upload Entries CSV Processor
Creates separate entries for each customer upload instance
"""
import csv
import hashlib
import logging
from datetime import datetime, date
from typing import Dict, List, Any, Optional, Tuple
from decimal import Decimal
from dataclasses import dataclass
from enum import Enum
from io import StringIO

from database.upload_entries_schema import CustomerUploadEntry, FileUpload, get_session

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ProcessingStatus(Enum):
    PROCESSED = "processed"
    ERROR = "error"
    DUPLICATE = "duplicate"

@dataclass
class CSVRow:
    """Represents a single CSV row data"""
    name: str
    phone: str
    loan_id: str
    amount: str
    due_date: str
    state: str
    cluster: str
    branch: str
    branch_contact_number: str
    employee: str
    employee_id: str
    employee_contact_number: str
    last_paid_date: str
    last_paid_amount: str
    due_amount: str

class UploadEntriesCSVProcessor:
    """CSV processor that creates separate upload entries for each customer upload"""
    
    def __init__(self, database_session):
        self.session = database_session
        
    def normalize_phone(self, phone: str) -> str:
        """Normalize phone number to +91 format"""
        if not phone:
            return ""
        
        # Remove all non-digit characters
        digits = ''.join(filter(str.isdigit, phone))
        
        # Handle different formats
        if len(digits) == 10:
            return f"+91{digits}"
        elif len(digits) == 12 and digits.startswith("91"):
            return f"+{digits}"
        elif len(digits) == 13 and digits.startswith("91"):
            return f"+{digits}"
        else:
            return f"+91{digits[-10:]}" if len(digits) >= 10 else phone
    
    def parse_date(self, date_str: str) -> Optional[date]:
        """Parse date string to date object"""
        if not date_str:
            return None
            
        # Try different date formats
        formats = [
            "%Y-%m-%d",
            "%d/%m/%Y", 
            "%m/%d/%Y",
            "%d-%m-%Y",
            "%Y-%m-%d %H:%M:%S"
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip(), fmt).date()
            except ValueError:
                continue
        
        logger.warning(f"Could not parse date: {date_str}")
        return None
    
    def parse_decimal(self, value: str) -> Optional[Decimal]:
        """Parse decimal value"""
        if not value:
            return None
        
        try:
            # Remove any currency symbols and commas
            clean_value = value.replace(',', '').replace('₹', '').replace('$', '').strip()
            return Decimal(clean_value)
        except (ValueError, decimal.InvalidOperation):
            logger.warning(f"Could not parse decimal: {value}")
            return None
    
    def compute_customer_fingerprint(self, name: str, phone: str) -> str:
        """Generate fingerprint for customer identification"""
        normalized_phone = self.normalize_phone(phone)
        normalized_name = name.strip().lower()
        fingerprint_data = f"{normalized_name}|{normalized_phone}"
        return hashlib.sha256(fingerprint_data.encode()).hexdigest()
    
    def parse_csv_data(self, file_data: bytes) -> List[CSVRow]:
        """Parse CSV data into structured rows"""
        try:
            # Decode the file data
            csv_content = file_data.decode('utf-8')
            csv_reader = csv.DictReader(StringIO(csv_content))
            
            rows = []
            for row_data in csv_reader:
                # Create CSVRow object
                csv_row = CSVRow(
                    name=row_data.get('name', '').strip(),
                    phone=row_data.get('phone', '').strip(),
                    loan_id=row_data.get('loan_id', '').strip(),
                    amount=row_data.get('amount', '').strip(),
                    due_date=row_data.get('due_date', '').strip(),
                    state=row_data.get('state', '').strip(),
                    cluster=row_data.get('Cluster', '').strip(),
                    branch=row_data.get('Branch', '').strip(),
                    branch_contact_number=row_data.get('Branch Contact Number', '').strip(),
                    employee=row_data.get('Employee', '').strip(),
                    employee_id=row_data.get('Employee ID', '').strip(),
                    employee_contact_number=row_data.get('Employee Contact Number', '').strip(),
                    last_paid_date=row_data.get('Last Paid Date', '').strip(),
                    last_paid_amount=row_data.get('Last Paid Amount', '').strip(),
                    due_amount=row_data.get('Due Amount', '').strip()
                )
                rows.append(csv_row)
            
            return rows
            
        except Exception as e:
            logger.error(f"Error parsing CSV data: {e}")
            raise
    
    def check_existing_customer(self, fingerprint: str) -> bool:
        """Check if customer already exists in the system"""
        from database.schemas import Customer
        existing = self.session.query(Customer).filter(
            Customer.fingerprint == fingerprint
        ).first()
        return existing is not None
    
    def check_existing_loan(self, loan_id: str) -> bool:
        """Check if loan already exists in the system"""
        from database.schemas import Loan
        existing = self.session.query(Loan).filter(
            Loan.loan_id == loan_id
        ).first()
        return existing is not None
    
    def process_upload_entries(
        self, 
        file_data: bytes, 
        filename: str, 
        uploaded_by: str = None,
        upload_timestamp: datetime = None
    ) -> Dict[str, Any]:
        """
        Process CSV upload and create individual upload entries
        Each customer appears as a separate entry for each upload
        """
        
        if upload_timestamp is None:
            upload_timestamp = datetime.utcnow()
        
        try:
            # Parse CSV data
            csv_rows = self.parse_csv_data(file_data)
            total_rows = len(csv_rows)
            
            logger.info(f"Processing {total_rows} rows from {filename}")
            
            # Create file upload record
            file_upload = FileUpload(
                filename=filename,
                original_filename=filename,
                uploaded_by=uploaded_by,
                uploaded_at=upload_timestamp,
                total_records=total_rows,
                status='processing'
            )
            
            self.session.add(file_upload)
            self.session.flush()  # Get the ID
            
            # Process each row and create upload entries
            processed_count = 0
            success_count = 0
            error_count = 0
            
            for row in csv_rows:
                try:
                    # Generate customer fingerprint
                    fingerprint = self.compute_customer_fingerprint(row.name, row.phone)
                    
                    # Check if this is a new customer or new loan
                    is_new_customer = not self.check_existing_customer(fingerprint)
                    is_new_loan = not self.check_existing_loan(row.loan_id)
                    
                    # Create upload entry (always create new entry regardless of existing data)
                    upload_entry = CustomerUploadEntry(
                        file_upload_id=file_upload.id,
                        upload_timestamp=upload_timestamp,
                        
                        # Customer information
                        customer_fingerprint=fingerprint,
                        full_name=row.name,
                        primary_phone=self.normalize_phone(row.phone),
                        state=row.state,
                        
                        # Loan information
                        loan_id=row.loan_id,
                        principal_amount=self.parse_decimal(row.amount),
                        outstanding_amount=self.parse_decimal(row.amount),
                        due_amount=self.parse_decimal(row.due_amount),
                        next_due_date=self.parse_date(row.due_date),
                        last_paid_date=self.parse_date(row.last_paid_date),
                        last_paid_amount=self.parse_decimal(row.last_paid_amount),
                        
                        # Branch and employee information
                        cluster=row.cluster,
                        branch=row.branch,
                        branch_contact_number=row.branch_contact_number,
                        employee_name=row.employee,
                        employee_id=row.employee_id,
                        employee_contact_number=row.employee_contact_number,
                        
                        # Metadata
                        is_new_customer=is_new_customer,
                        is_new_loan=is_new_loan,
                        processing_status='processed'
                    )
                    
                    self.session.add(upload_entry)
                    success_count += 1
                    
                except Exception as row_error:
                    logger.error(f"Error processing row {processed_count + 1}: {row_error}")
                    error_count += 1
                
                processed_count += 1
            
            # Update file upload statistics
            file_upload.processed_records = processed_count
            file_upload.success_records = success_count
            file_upload.failed_records = error_count
            file_upload.status = 'completed'
            
            # Commit all changes
            self.session.commit()
            
            result = {
                'success': True,
                'file_upload_id': str(file_upload.id),
                'total_records': total_rows,
                'processed_records': processed_count,
                'success_records': success_count,
                'failed_records': error_count,
                'upload_timestamp': upload_timestamp.isoformat(),
                'message': f'Successfully processed {success_count}/{total_rows} records'
            }
            
            logger.info(f"Upload processing completed: {result}")
            return result
            
        except Exception as e:
            self.session.rollback()
            logger.error(f"Error processing upload: {e}")
            raise

# Example usage and testing
def create_sample_upload_entries():
    """Create sample upload entries for testing"""
    
    session = get_session()
    processor = UploadEntriesCSVProcessor(session)
    
    try:
        # Sample CSV data for yesterday
        yesterday_csv = """name,phone,loan_id,amount,due_date,state,Cluster,Branch,Branch Contact Number,Employee,Employee ID,Employee Contact Number,Last Paid Date,Last Paid Amount,Due Amount
Haku,9876543210,HAKU_LOAN_001,100000,2024-01-15,Karnataka,Test Cluster,Test Branch,08012345678,Test Employee,EMP999,09012345678,2023-12-10,5000,5000"""
        
        # Sample CSV data for today (same customer, different loan)
        today_csv = """name,phone,loan_id,amount,due_date,state,Cluster,Branch,Branch Contact Number,Employee,Employee ID,Employee Contact Number,Last Paid Date,Last Paid Amount,Due Amount
Haku,9876543210,HAKU_LOAN_002,150000,2024-02-15,Karnataka,Test Cluster,Test Branch,08012345678,Test Employee,EMP999,09012345678,2024-01-10,8000,8000"""
        
        from datetime import timedelta
        import pytz
        
        IST = pytz.timezone('Asia/Kolkata')
        today_ist = datetime.now(IST).replace(hour=10, minute=0, second=0, microsecond=0)
        yesterday_ist = today_ist - timedelta(days=1)
        
        # Convert to UTC for database storage
        today_utc = today_ist.astimezone(pytz.UTC).replace(tzinfo=None)
        yesterday_utc = yesterday_ist.astimezone(pytz.UTC).replace(tzinfo=None)
        
        # Process yesterday's upload
        result1 = processor.process_upload_entries(
            file_data=yesterday_csv.encode('utf-8'),
            filename="haku_yesterday_upload.csv",
            uploaded_by="test_user",
            upload_timestamp=yesterday_utc
        )
        
        # Process today's upload
        result2 = processor.process_upload_entries(
            file_data=today_csv.encode('utf-8'),
            filename="haku_today_upload.csv", 
            uploaded_by="test_user",
            upload_timestamp=today_utc
        )
        
        print("✅ Sample upload entries created successfully!")
        print(f"Yesterday upload: {result1}")
        print(f"Today upload: {result2}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error creating sample upload entries: {e}")
        return False
    finally:
        session.close()

if __name__ == "__main__":
    print("🧪 Upload Entries CSV Processor")
    create_sample_upload_entries()
