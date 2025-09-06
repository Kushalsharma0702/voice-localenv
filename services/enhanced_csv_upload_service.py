"""
Enhanced CSV Upload Service
Integrates with the new schema and CSV processor for comprehensive customer/loan management
"""
import os
import io
import pandas as pd
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv

from database.schemas import get_session, FileUpload, Customer, Loan
from services.enhanced_csv_processor import EnhancedCSVProcessor, ProcessingStatus
from utils.redis_session import redis_manager
from utils.logger import logger

load_dotenv()

class EnhancedCSVUploadService:
    """Enhanced CSV upload service for new schema format"""
    
    def __init__(self):
        self.redis_manager = redis_manager
        
    async def upload_and_process_csv(
        self, 
        file_data: bytes, 
        filename: str, 
        uploaded_by: str = None,
        websocket_id: str = None
    ) -> Dict[str, Any]:
        """
        Process uploaded CSV file with new format:
        name,phone,loan_id,amount,due_date,state,Cluster,Branch,Branch Contact Number,
        Employee,Employee ID,Employee Contact Number,Last Paid Date,Last Paid Amount,Due Amount
        """
        session = get_session()
        try:
            logger.app.info(f"🔄 Starting CSV upload processing: {filename}")
            
            # Create file upload record
            file_upload = FileUpload(
                filename=filename,
                original_filename=filename,
                uploaded_by=uploaded_by,
                status='processing'
            )
            session.add(file_upload)
            session.commit()
            session.refresh(file_upload)
            
            upload_id = str(file_upload.id)
            logger.app.info(f"📋 Created file upload record: {upload_id}")
            
            # Initialize CSV processor
            csv_processor = EnhancedCSVProcessor(session)
            
            # Parse CSV data
            csv_data = await self._parse_csv_file(file_data, filename)
            total_records = len(csv_data)
            
            file_upload.total_records = total_records
            session.commit()
            
            logger.app.info(f"📊 Processing {total_records} CSV rows")
            
            # Process each CSV row
            processing_results = {
                'total_records': total_records,
                'processed_records': 0,
                'success_records': 0,
                'failed_records': 0,
                'new_customers': 0,
                'updated_customers': 0,
                'new_loans': 0,
                'updated_loans': 0,
                'duplicate_records': 0,
                'errors': []
            }
            
            for line_number, row_data in enumerate(csv_data, 1):
                try:
                    # Update progress via WebSocket
                    if websocket_id:
                        await self._send_progress_update(
                            websocket_id, 
                            line_number, 
                            total_records, 
                            f"Processing row {line_number}"
                        )
                    
                    # Parse CSV row
                    csv_row = csv_processor.parse_csv_row(row_data, line_number)
                    
                    if csv_row.status == ProcessingStatus.ERROR:
                        processing_results['failed_records'] += 1
                        processing_results['errors'].append({
                            'line': line_number,
                            'error': csv_row.error_message,
                            'data': row_data
                        })
                        continue
                    
                    # Process customer
                    customer, is_new_customer = csv_processor.create_or_update_customer(csv_row)
                    if is_new_customer:
                        processing_results['new_customers'] += 1
                    else:
                        processing_results['updated_customers'] += 1
                    
                    # Process loan
                    loan, is_new_loan = csv_processor.create_or_update_loan(customer, csv_row)
                    if is_new_loan:
                        processing_results['new_loans'] += 1
                    else:
                        processing_results['updated_loans'] += 1
                    
                    # Save upload record
                    csv_processor.save_upload_record(upload_id, csv_row)
                    
                    csv_row.status = ProcessingStatus.MATCHED
                    processing_results['success_records'] += 1
                    processing_results['processed_records'] += 1
                    
                except Exception as e:
                    logger.app.error(f"❌ Error processing row {line_number}: {e}")
                    processing_results['failed_records'] += 1
                    processing_results['errors'].append({
                        'line': line_number,
                        'error': str(e),
                        'data': row_data
                    })
            
            # Update file upload record with final results
            file_upload.processed_records = processing_results['processed_records']
            file_upload.success_records = processing_results['success_records']
            file_upload.failed_records = processing_results['failed_records']
            file_upload.status = 'completed' if processing_results['failed_records'] == 0 else 'completed_with_errors'
            file_upload.processing_errors = processing_results['errors']
            
            session.commit()
            
            # Final progress update
            if websocket_id:
                await self._send_progress_update(
                    websocket_id, 
                    total_records, 
                    total_records, 
                    "Processing completed"
                )
            
            logger.app.info(f"✅ CSV processing completed: {processing_results}")
            
            return {
                'success': True,
                'upload_id': upload_id,
                'filename': filename,
                'processing_results': processing_results,
                'message': f"Successfully processed {processing_results['success_records']}/{total_records} records"
            }
            
        except Exception as e:
            logger.app.error(f"💥 Critical error in CSV upload: {e}")
            
            # Update file upload record with error
            if 'file_upload' in locals():
                file_upload.status = 'failed'
                file_upload.processing_errors = [{'error': str(e)}]
                session.commit()
            
            return {
                'success': False,
                'error': str(e),
                'message': f"Failed to process CSV file: {str(e)}"
            }
            
        finally:
            session.close()
    
    async def _parse_csv_file(self, file_data: bytes, filename: str) -> List[Dict[str, Any]]:
        """Parse CSV file into list of dictionaries"""
        try:
            # Read CSV data
            csv_content = io.StringIO(file_data.decode('utf-8'))
            df = pd.read_csv(csv_content)
            
            # Expected columns for new CSV format
            expected_columns = [
                'name', 'phone', 'loan_id', 'amount', 'due_date', 'state',
                'Cluster', 'Branch', 'Branch Contact Number', 'Employee',
                'Employee ID', 'Employee Contact Number', 'Last Paid Date',
                'Last Paid Amount', 'Due Amount'
            ]
            
            logger.app.info(f"📋 CSV columns found: {list(df.columns)}")
            logger.app.info(f"📋 Expected columns: {expected_columns}")
            
            # Convert DataFrame to list of dictionaries
            csv_data = df.to_dict('records')
            
            # Replace NaN values with None for proper JSON serialization
            import numpy as np
            for row in csv_data:
                for key, value in row.items():
                    if pd.isna(value) or (isinstance(value, float) and np.isnan(value)):
                        row[key] = None
            
            logger.app.info(f"📊 Parsed {len(csv_data)} rows from CSV")
            return csv_data
            
        except Exception as e:
            logger.app.error(f"❌ Error parsing CSV file: {e}")
            raise ValueError(f"Invalid CSV file format: {str(e)}")
    
    async def _send_progress_update(
        self, 
        websocket_id: str, 
        current: int, 
        total: int, 
        message: str
    ):
        """Send progress update via WebSocket"""
        try:
            progress_data = {
                'type': 'upload_progress',
                'current': current,
                'total': total,
                'percentage': round((current / total) * 100, 1),
                'message': message
            }
            
            await self.redis_manager.publish_to_websocket(websocket_id, progress_data)
            
        except Exception as e:
            logger.app.warning(f"⚠️  Failed to send progress update: {e}")

# Global service instance
enhanced_csv_service = EnhancedCSVUploadService()
