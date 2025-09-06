"""
Enhanced Banking Call Management Service
Comprehensive service for file uploads, customer/loan management,
call tracking, and campaign management with deduplication and audit trails.
"""

import uuid
import json
import pandas as pd
import asyncio
from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional, List, Tuple
import httpx
import os
from io import BytesIO
from urllib.parse import urlencode
from dotenv import load_dotenv

from database.enhanced_banking_schemas import (
    init_database, get_session, Customer, Loan, DailyUpload, UploadRecord,
    CallCampaign, CallSession, CallAttempt, CustomerDailyCallStats,
    CustomerCallPreferences, CustomerAuditLog, LoanAuditLog,
    compute_customer_fingerprint, compute_upload_record_fingerprint,
    get_customer_call_eligibility, get_upload_processing_summary
)
from utils.redis_session import redis_manager
from utils.logger import logger

load_dotenv()


class EnhancedBankingCallService:
    """Enhanced call management service with comprehensive tracking"""
    
    def __init__(self):
        self.redis_manager = redis_manager
        
        # Exotel configuration
        self.exotel_sid = os.getenv("EXOTEL_SID")
        self.exotel_token = os.getenv("EXOTEL_TOKEN")
        self.exotel_api_key = os.getenv("EXOTEL_API_KEY")
        self.exotel_virtual_number = os.getenv("EXOTEL_VIRTUAL_NUMBER")
        self.exotel_flow_app_id = os.getenv("EXOTEL_FLOW_APP_ID")
        self.agent_phone_number = os.getenv("AGENT_PHONE_NUMBER")
        
        # Initialize database
        init_database()
    
    async def process_daily_upload(
        self, 
        file_data: bytes, 
        filename: str, 
        uploaded_by: str = None,
        business_date: date = None,
        websocket_id: str = None
    ) -> Dict[str, Any]:
        """
        Process daily customer/loan data upload with comprehensive tracking
        
        Expected CSV columns:
        - customer_reference_id, full_name, primary_phone, national_id, email
        - loan_account_number, loan_type, principal_amount, outstanding_amount
        - emi_amount, next_due_date, days_past_due, bucket_category, etc.
        """
        session = get_session()
        
        try:
            # Create daily upload record
            upload = DailyUpload(
                upload_date=date.today(),
                file_name=filename,
                original_file_name=filename,
                file_size_bytes=len(file_data),
                uploaded_by=uploaded_by or "system",
                upload_source="MANUAL",
                business_date=business_date or date.today(),
                processing_status="PROCESSING",
                processing_start_time=datetime.utcnow()
            )
            session.add(upload)
            session.commit()
            session.refresh(upload)
            
            logger.info(f"Started processing upload {upload.id} - {filename}")
            
            # Parse file
            try:
                # Detect file type and parse
                if filename.lower().endswith('.csv'):
                    df = pd.read_csv(BytesIO(file_data))
                elif filename.lower().endswith(('.xlsx', '.xls')):
                    df = pd.read_excel(BytesIO(file_data))
                else:
                    raise ValueError("Unsupported file format. Use CSV or Excel files.")
                
                # Convert to records
                records = df.to_dict('records')
                upload.total_records = len(records)
                
            except Exception as e:
                upload.processing_status = "FAILED"
                upload.validation_errors = {"parsing_error": str(e)}
                session.commit()
                return {"success": False, "error": f"File parsing failed: {str(e)}"}
            
            # Process records
            processing_stats = {
                "new_customers": 0,
                "updated_customers": 0,
                "new_loans": 0,
                "updated_loans": 0,
                "duplicate_records": 0,
                "error_records": 0,
                "processed_records": 0
            }
            
            processing_errors = []
            
            for idx, record in enumerate(records):
                try:
                    result = await self._process_upload_record(
                        session, upload.id, idx + 1, record
                    )
                    
                    # Update stats
                    if result["status"] == "new_customer":
                        processing_stats["new_customers"] += 1
                    elif result["status"] == "updated_customer":
                        processing_stats["updated_customers"] += 1
                    elif result["status"] == "new_loan":
                        processing_stats["new_loans"] += 1
                    elif result["status"] == "updated_loan":
                        processing_stats["updated_loans"] += 1
                    elif result["status"] == "duplicate":
                        processing_stats["duplicate_records"] += 1
                    
                    processing_stats["processed_records"] += 1
                    
                    # Send progress update via WebSocket
                    if websocket_id and idx % 10 == 0:  # Update every 10 records
                        await self._send_upload_progress(
                            websocket_id, upload.id, idx + 1, len(records), processing_stats
                        )
                        
                except Exception as e:
                    processing_stats["error_records"] += 1
                    processing_errors.append({
                        "row": idx + 1,
                        "data": record,
                        "error": str(e)
                    })
                    logger.error(f"Error processing record {idx + 1}: {str(e)}")
            
            # Update upload record with final stats
            upload.processed_records = processing_stats["processed_records"]
            upload.new_customers = processing_stats["new_customers"]
            upload.updated_customers = processing_stats["updated_customers"]
            upload.new_loans = processing_stats["new_loans"]
            upload.updated_loans = processing_stats["updated_loans"]
            upload.duplicate_records = processing_stats["duplicate_records"]
            upload.error_records = processing_stats["error_records"]
            upload.processing_status = "COMPLETED" if processing_stats["error_records"] == 0 else "PARTIAL_SUCCESS"
            upload.processing_end_time = datetime.utcnow()
            upload.validation_errors = processing_errors if processing_errors else None
            upload.processing_summary = processing_stats
            
            session.commit()
            
            logger.info(f"Completed processing upload {upload.id}: {processing_stats}")
            
            return {
                "success": True,
                "upload_id": str(upload.id),
                "stats": processing_stats,
                "summary": get_upload_processing_summary(session, upload.id)
            }
            
        except Exception as e:
            logger.error(f"Upload processing failed: {str(e)}")
            session.rollback()
            return {"success": False, "error": str(e)}
        finally:
            session.close()
    
    async def _process_upload_record(
        self, 
        session, 
        upload_id: uuid.UUID, 
        row_number: int, 
        record: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Process a single upload record"""
        
        # Generate fingerprint for deduplication
        fingerprint = compute_upload_record_fingerprint(record)
        
        # Create upload record
        upload_record = UploadRecord(
            daily_upload_id=upload_id,
            row_number=row_number,
            raw_data=record,
            fingerprint=fingerprint,
            parsed_customer_ref=record.get('customer_reference_id'),
            parsed_loan_account=record.get('loan_account_number'),
            parsed_phone=self._normalize_phone(record.get('primary_phone')),
            parsed_national_id=record.get('national_id'),
            parsed_name=record.get('full_name')
        )
        
        try:
            # Check for duplicates within this upload
            existing_record = session.query(UploadRecord).filter_by(
                daily_upload_id=upload_id,
                fingerprint=fingerprint
            ).first()
            
            if existing_record:
                upload_record.is_duplicate = True
                upload_record.duplicate_of = existing_record.id
                upload_record.record_status = "DUPLICATE"
                session.add(upload_record)
                return {"status": "duplicate"}
            
            # Find or create customer
            customer_result = await self._find_or_create_customer(session, record, upload_id)
            customer = customer_result["customer"]
            upload_record.matched_customer_id = customer.id
            upload_record.match_method = customer_result["method"]
            upload_record.match_confidence = customer_result["confidence"]
            
            # Find or create loan
            loan_result = await self._find_or_create_loan(session, customer, record, upload_id)
            loan = loan_result["loan"]
            upload_record.matched_loan_id = loan.id
            
            upload_record.record_status = "MATCHED"
            upload_record.processed_at = datetime.utcnow()
            session.add(upload_record)
            
            return {
                "status": customer_result["action"] or loan_result["action"],
                "customer_id": str(customer.id),
                "loan_id": str(loan.id)
            }
            
        except Exception as e:
            upload_record.record_status = "ERROR"
            upload_record.processing_errors = {"error": str(e)}
            session.add(upload_record)
            raise e
    
    async def _find_or_create_customer(
        self, 
        session, 
        record: Dict[str, Any], 
        upload_id: uuid.UUID
    ) -> Dict[str, Any]:
        """Find existing customer or create new one"""
        
        # Generate customer fingerprint
        customer_fingerprint = compute_customer_fingerprint(
            record.get('primary_phone'),
            record.get('national_id'),
            record.get('customer_reference_id')
        )
        
        # Try to find existing customer
        customer = None
        match_method = "NONE"
        match_confidence = 0.0
        
        # 1. Try exact fingerprint match
        customer = session.query(Customer).filter_by(fingerprint=customer_fingerprint).first()
        if customer:
            match_method = "FINGERPRINT"
            match_confidence = 1.0
            # Update customer with new data
            await self._update_customer_from_record(session, customer, record, upload_id)
            return {"customer": customer, "method": match_method, "confidence": match_confidence, "action": "updated_customer"}
        
        # 2. Try customer reference ID match
        if record.get('customer_reference_id'):
            customer = session.query(Customer).filter_by(
                customer_reference_id=record['customer_reference_id']
            ).first()
            if customer:
                match_method = "CUSTOMER_REF"
                match_confidence = 0.95
                await self._update_customer_from_record(session, customer, record, upload_id)
                return {"customer": customer, "method": match_method, "confidence": match_confidence, "action": "updated_customer"}
        
        # 3. Try phone number match
        normalized_phone = self._normalize_phone(record.get('primary_phone'))
        if normalized_phone:
            customer = session.query(Customer).filter_by(primary_phone=normalized_phone).first()
            if customer:
                match_method = "PHONE"
                match_confidence = 0.8
                await self._update_customer_from_record(session, customer, record, upload_id)
                return {"customer": customer, "method": match_method, "confidence": match_confidence, "action": "updated_customer"}
        
        # 4. Create new customer
        customer = Customer(
            customer_reference_id=record.get('customer_reference_id') or str(uuid.uuid4()),
            fingerprint=customer_fingerprint,
            full_name=record.get('full_name'),
            primary_phone=normalized_phone,
            alternate_phone=record.get('alternate_phone'),
            email=record.get('email'),
            national_id=record.get('national_id'),
            date_of_birth=self._parse_date(record.get('date_of_birth')),
            address=record.get('address'),
            city=record.get('city'),
            state=record.get('state'),
            pincode=record.get('pincode'),
            preferred_language=record.get('preferred_language', 'en'),
            risk_category=record.get('risk_category'),
            customer_status='ACTIVE',
            first_onboarded_date=date.today(),
            kyc_status=record.get('kyc_status', 'PENDING')
        )
        
        session.add(customer)
        session.flush()  # Get the ID
        
        # Create audit log
        audit_log = CustomerAuditLog(
            customer_id=customer.id,
            changed_by="system",
            change_type="INSERT",
            new_values=record,
            change_reason="Daily upload",
            source_system="CSV_UPLOAD",
            upload_id=upload_id
        )
        session.add(audit_log)
        
        return {"customer": customer, "method": "NEW", "confidence": 1.0, "action": "new_customer"}
    
    async def _find_or_create_loan(
        self, 
        session, 
        customer: Customer, 
        record: Dict[str, Any], 
        upload_id: uuid.UUID
    ) -> Dict[str, Any]:
        """Find existing loan or create new one"""
        
        loan_account_number = record.get('loan_account_number')
        if not loan_account_number:
            raise ValueError("loan_account_number is required")
        
        # Try to find existing loan
        loan = session.query(Loan).filter_by(loan_account_number=loan_account_number).first()
        
        if loan:
            # Update existing loan
            await self._update_loan_from_record(session, loan, record, upload_id)
            return {"loan": loan, "action": "updated_loan"}
        
        # Create new loan
        loan = Loan(
            customer_id=customer.id,
            loan_account_number=loan_account_number,
            loan_type=record.get('loan_type', 'PERSONAL'),
            product_code=record.get('product_code'),
            principal_amount=self._parse_decimal(record.get('principal_amount')),
            outstanding_amount=self._parse_decimal(record.get('outstanding_amount')),
            emi_amount=self._parse_decimal(record.get('emi_amount')),
            interest_rate=self._parse_decimal(record.get('interest_rate')),
            tenure_months=self._parse_int(record.get('tenure_months')),
            disbursement_date=self._parse_date(record.get('disbursement_date')),
            maturity_date=self._parse_date(record.get('maturity_date')),
            next_due_date=self._parse_date(record.get('next_due_date')),
            days_past_due=self._parse_int(record.get('days_past_due', 0)),
            bucket_category=record.get('bucket_category'),
            loan_status=record.get('loan_status', 'ACTIVE'),
            branch_code=record.get('branch_code'),
            relationship_manager=record.get('relationship_manager'),
            collection_priority=self._parse_int(record.get('collection_priority', 5)),
            last_payment_date=self._parse_date(record.get('last_payment_date')),
            last_payment_amount=self._parse_decimal(record.get('last_payment_amount'))
        )
        
        session.add(loan)
        session.flush()
        
        # Create audit log
        audit_log = LoanAuditLog(
            loan_id=loan.id,
            changed_by="system",
            change_type="INSERT",
            new_values=record,
            change_reason="Daily upload",
            source_system="CSV_UPLOAD",
            upload_id=upload_id
        )
        session.add(audit_log)
        
        return {"loan": loan, "action": "new_loan"}
    
    async def create_call_campaign(
        self,
        campaign_name: str,
        campaign_type: str,
        upload_id: uuid.UUID = None,
        target_criteria: Dict[str, Any] = None,
        created_by: str = "system"
    ) -> Dict[str, Any]:
        """Create a new call campaign with targeting criteria"""
        
        session = get_session()
        try:
            campaign = CallCampaign(
                campaign_name=campaign_name,
                campaign_type=campaign_type,
                upload_id=upload_id,
                target_bucket_categories=target_criteria.get('bucket_categories', []) if target_criteria else [],
                target_states=target_criteria.get('states', []) if target_criteria else [],
                priority_level=target_criteria.get('priority_level', 5) if target_criteria else 5,
                max_attempts_per_customer=target_criteria.get('max_attempts', 3) if target_criteria else 3,
                min_gap_hours=target_criteria.get('min_gap_hours', 24) if target_criteria else 24,
                campaign_start_date=target_criteria.get('start_date') if target_criteria else date.today(),
                campaign_end_date=target_criteria.get('end_date') if target_criteria else None,
                campaign_status='DRAFT',
                created_by=created_by
            )
            
            session.add(campaign)
            session.commit()
            session.refresh(campaign)
            
            logger.info(f"Created call campaign {campaign.id}: {campaign_name}")
            
            return {
                "success": True,
                "campaign_id": str(campaign.id),
                "campaign": {
                    "id": str(campaign.id),
                    "name": campaign.campaign_name,
                    "type": campaign.campaign_type,
                    "status": campaign.campaign_status,
                    "target_criteria": target_criteria
                }
            }
            
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to create campaign: {str(e)}")
            return {"success": False, "error": str(e)}
        finally:
            session.close()
    
    async def trigger_loan_call(
        self,
        loan_id: uuid.UUID,
        campaign_id: uuid.UUID = None,
        call_type: str = "COLLECTION"
    ) -> Dict[str, Any]:
        """Trigger an outbound call for a specific loan"""
        
        session = get_session()
        try:
            # Get loan and customer details
            loan = session.query(Loan).filter_by(id=loan_id).first()
            if not loan:
                return {"success": False, "error": "Loan not found"}
            
            customer = loan.customer
            if not customer:
                return {"success": False, "error": "Customer not found for loan"}
            
            # Check call eligibility
            eligibility = get_customer_call_eligibility(session, customer.id)
            if not eligibility['eligible']:
                return {"success": False, "error": f"Customer not eligible: {eligibility['reason']}"}
            
            # Create call session
            call_session = CallSession(
                campaign_id=campaign_id,
                customer_id=customer.id,
                loan_id=loan.id,
                call_direction="OUTBOUND",
                to_number=customer.primary_phone,
                from_number=self.exotel_virtual_number,
                call_status="INITIATED"
            )
            
            session.add(call_session)
            session.flush()
            
            # Make the actual call via Exotel
            call_result = await self._initiate_exotel_call(
                customer.primary_phone,
                call_session.id
            )
            
            if call_result["success"]:
                call_session.call_sid = call_result["call_sid"]
                call_session.call_status = "RINGING"
                
                # Update daily stats
                await self._update_customer_daily_stats(session, customer.id, "attempted")
                
                session.commit()
                
                logger.info(f"Call initiated for loan {loan_id}, call_sid: {call_result['call_sid']}")
                
                return {
                    "success": True,
                    "call_session_id": str(call_session.id),
                    "call_sid": call_result["call_sid"],
                    "customer_name": customer.full_name,
                    "phone_number": customer.primary_phone,
                    "loan_account": loan.loan_account_number
                }
            else:
                call_session.call_status = "FAILED"
                call_session.call_metadata = {"error": call_result["error"]}
                session.commit()
                
                return {"success": False, "error": call_result["error"]}
                
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to trigger call for loan {loan_id}: {str(e)}")
            return {"success": False, "error": str(e)}
        finally:
            session.close()
    
    async def get_call_analytics(
        self,
        date_from: date = None,
        date_to: date = None,
        group_by: str = "day"
    ) -> Dict[str, Any]:
        """Get comprehensive call analytics"""
        
        session = get_session()
        try:
            if not date_from:
                date_from = date.today() - timedelta(days=30)
            if not date_to:
                date_to = date.today()
            
            # Daily call statistics
            daily_stats = session.query(CustomerDailyCallStats).filter(
                CustomerDailyCallStats.stat_date >= date_from,
                CustomerDailyCallStats.stat_date <= date_to
            ).all()
            
            # Call sessions analytics
            call_sessions = session.query(CallSession).filter(
                CallSession.initiated_at >= datetime.combine(date_from, datetime.min.time()),
                CallSession.initiated_at <= datetime.combine(date_to, datetime.max.time())
            ).all()
            
            # Aggregate data
            analytics = {
                "date_range": {"from": date_from.isoformat(), "to": date_to.isoformat()},
                "total_calls": len(call_sessions),
                "unique_customers": len(set(cs.customer_id for cs in call_sessions)),
                "call_status_breakdown": {},
                "daily_breakdown": {},
                "campaign_breakdown": {},
                "loan_type_breakdown": {}
            }
            
            # Status breakdown
            for session_obj in call_sessions:
                status = session_obj.call_status or "UNKNOWN"
                analytics["call_status_breakdown"][status] = analytics["call_status_breakdown"].get(status, 0) + 1
            
            # Daily breakdown
            for session_obj in call_sessions:
                day = session_obj.initiated_at.date().isoformat()
                if day not in analytics["daily_breakdown"]:
                    analytics["daily_breakdown"][day] = {"total": 0, "completed": 0, "failed": 0}
                
                analytics["daily_breakdown"][day]["total"] += 1
                if session_obj.call_status == "COMPLETED":
                    analytics["daily_breakdown"][day]["completed"] += 1
                elif session_obj.call_status in ["FAILED", "NO_ANSWER", "BUSY"]:
                    analytics["daily_breakdown"][day]["failed"] += 1
            
            return analytics
            
        except Exception as e:
            logger.error(f"Failed to get analytics: {str(e)}")
            return {"error": str(e)}
        finally:
            session.close()
    
    # Utility methods
    def _normalize_phone(self, phone: str) -> Optional[str]:
        """Normalize phone number to standard format"""
        if not phone:
            return None
        
        # Remove all non-digits
        digits = ''.join(filter(str.isdigit, str(phone)))
        
        # Handle Indian numbers
        if digits.startswith('91') and len(digits) == 12:
            return digits[-10:]  # Return last 10 digits
        elif len(digits) == 10:
            return digits
        
        return None
    
    def _parse_date(self, date_str) -> Optional[date]:
        """Parse date string to date object"""
        if not date_str:
            return None
        
        try:
            if isinstance(date_str, str):
                # Try common date formats
                for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d']:
                    try:
                        return datetime.strptime(date_str, fmt).date()
                    except ValueError:
                        continue
            return None
        except:
            return None
    
    def _parse_decimal(self, value) -> Optional[float]:
        """Parse decimal value"""
        if value is None or value == '':
            return None
        try:
            return float(value)
        except:
            return None
    
    def _parse_int(self, value) -> Optional[int]:
        """Parse integer value"""
        if value is None or value == '':
            return None
        try:
            return int(value)
        except:
            return None
    
    async def _update_customer_from_record(
        self, 
        session, 
        customer: Customer, 
        record: Dict[str, Any], 
        upload_id: uuid.UUID
    ):
        """Update customer with new data from upload record"""
        
        old_values = {
            "full_name": customer.full_name,
            "email": customer.email,
            "address": customer.address,
            "city": customer.city,
            "state": customer.state,
            "pincode": customer.pincode
        }
        
        # Update fields if new data is provided
        if record.get('full_name'):
            customer.full_name = record['full_name']
        if record.get('email'):
            customer.email = record['email']
        if record.get('address'):
            customer.address = record['address']
        if record.get('city'):
            customer.city = record['city']
        if record.get('state'):
            customer.state = record['state']
        if record.get('pincode'):
            customer.pincode = record['pincode']
        
        customer.updated_at = datetime.utcnow()
        
        # Create audit log
        audit_log = CustomerAuditLog(
            customer_id=customer.id,
            changed_by="system",
            change_type="UPDATE",
            old_values=old_values,
            new_values=record,
            change_reason="Daily upload update",
            source_system="CSV_UPLOAD",
            upload_id=upload_id
        )
        session.add(audit_log)
    
    async def _update_loan_from_record(
        self, 
        session, 
        loan: Loan, 
        record: Dict[str, Any], 
        upload_id: uuid.UUID
    ):
        """Update loan with new data from upload record"""
        
        old_values = {
            "outstanding_amount": float(loan.outstanding_amount) if loan.outstanding_amount else None,
            "next_due_date": loan.next_due_date.isoformat() if loan.next_due_date else None,
            "days_past_due": loan.days_past_due,
            "bucket_category": loan.bucket_category,
            "loan_status": loan.loan_status
        }
        
        # Update fields
        if record.get('outstanding_amount'):
            loan.outstanding_amount = self._parse_decimal(record['outstanding_amount'])
        if record.get('next_due_date'):
            loan.next_due_date = self._parse_date(record['next_due_date'])
        if record.get('days_past_due'):
            loan.days_past_due = self._parse_int(record['days_past_due'])
        if record.get('bucket_category'):
            loan.bucket_category = record['bucket_category']
        if record.get('loan_status'):
            loan.loan_status = record['loan_status']
        
        loan.updated_at = datetime.utcnow()
        
        # Create audit log
        audit_log = LoanAuditLog(
            loan_id=loan.id,
            changed_by="system",
            change_type="UPDATE",
            old_values=old_values,
            new_values=record,
            change_reason="Daily upload update",
            source_system="CSV_UPLOAD",
            upload_id=upload_id
        )
        session.add(audit_log)
    
    async def _initiate_exotel_call(self, phone_number: str, call_session_id: uuid.UUID) -> Dict[str, Any]:
        """Initiate call via Exotel API"""
        
        try:
            url = f"https://api.exotel.com/v1/Accounts/{self.exotel_sid}/Calls/connect.json"
            
            data = {
                'From': self.exotel_virtual_number,
                'To': phone_number,
                'CallType': 'trans',
                'AppId': self.exotel_flow_app_id,
                'StatusCallback': f"{os.getenv('BASE_URL')}/api/call-status-webhook",
                'StatusCallbackMethod': 'POST',
                'CustomField': str(call_session_id)
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    data=data,
                    auth=(self.exotel_api_key, self.exotel_token),
                    timeout=30
                )
                
                if response.status_code == 200:
                    result = response.json()
                    call_sid = result.get('Call', {}).get('Sid')
                    
                    if call_sid:
                        return {"success": True, "call_sid": call_sid}
                    else:
                        return {"success": False, "error": "No call SID returned"}
                else:
                    return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}
                    
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _update_customer_daily_stats(self, session, customer_id: uuid.UUID, event_type: str):
        """Update customer daily call statistics"""
        
        today = date.today()
        
        # Get or create daily stats record
        stats = session.query(CustomerDailyCallStats).filter_by(
            customer_id=customer_id,
            stat_date=today
        ).first()
        
        if not stats:
            stats = CustomerDailyCallStats(
                customer_id=customer_id,
                stat_date=today
            )
            session.add(stats)
        
        # Update based on event type
        if event_type == "attempted":
            stats.total_calls_attempted += 1
        elif event_type == "successful":
            stats.successful_calls += 1
            stats.last_successful_contact = datetime.utcnow()
        elif event_type == "failed":
            stats.failed_calls += 1
        
        stats.updated_at = datetime.utcnow()
    
    async def _send_upload_progress(
        self, 
        websocket_id: str, 
        upload_id: uuid.UUID, 
        processed: int, 
        total: int, 
        stats: Dict[str, Any]
    ):
        """Send upload progress via WebSocket"""
        
        try:
            progress_data = {
                "type": "upload_progress",
                "upload_id": str(upload_id),
                "processed": processed,
                "total": total,
                "progress_percent": (processed / total) * 100,
                "stats": stats
            }
            
            # Use Redis to send WebSocket message
            await self.redis_manager.publish_to_websocket(websocket_id, progress_data)
            
        except Exception as e:
            logger.error(f"Failed to send progress update: {str(e)}")


# Global service instance
banking_service = EnhancedBankingCallService()
