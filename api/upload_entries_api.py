#!/usr/bin/env python3
"""
Upload Entries API
Provides endpoints for querying upload entries with date filtering
Each customer upload appears as a separate entry
"""
from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, Query, HTTPException
import pytz

from database.upload_entries_schema import CustomerUploadEntry, FileUpload, get_session

# IST timezone setup
IST = pytz.timezone('Asia/Kolkata')

def format_ist_datetime(dt):
    """Format datetime to IST string"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Assume UTC if no timezone info
        dt = dt.replace(tzinfo=pytz.UTC)
    ist_dt = dt.astimezone(IST)
    return ist_dt.strftime('%Y-%m-%d %H:%M:%S IST')

def get_date_range_utc(date_filter: str) -> tuple[datetime, datetime]:
    """Get UTC date range for filtering"""
    today_ist = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    
    if date_filter == 'today':
        start_ist = today_ist
        end_ist = today_ist.replace(hour=23, minute=59, second=59)
    elif date_filter == 'yesterday':
        yesterday_ist = today_ist - timedelta(days=1)
        start_ist = yesterday_ist
        end_ist = yesterday_ist.replace(hour=23, minute=59, second=59)
    elif date_filter == 'this-week':
        week_start = today_ist - timedelta(days=today_ist.weekday())
        start_ist = week_start
        end_ist = today_ist.replace(hour=23, minute=59, second=59)
    elif date_filter == 'last-week':
        last_week_start = today_ist - timedelta(days=today_ist.weekday() + 7)
        last_week_end = last_week_start + timedelta(days=6)
        start_ist = last_week_start
        end_ist = last_week_end.replace(hour=23, minute=59, second=59)
    elif date_filter == 'this-month':
        month_start = today_ist.replace(day=1)
        start_ist = month_start
        end_ist = today_ist.replace(hour=23, minute=59, second=59)
    else:
        # Default to today
        start_ist = today_ist
        end_ist = today_ist.replace(hour=23, minute=59, second=59)
    
    # Convert to UTC for database query
    start_utc = start_ist.astimezone(pytz.UTC).replace(tzinfo=None)
    end_utc = end_ist.astimezone(pytz.UTC).replace(tzinfo=None)
    
    return start_utc, end_utc

async def get_upload_entries(
    date_filter: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search: Optional[str] = None,
    state: Optional[str] = None,
    cluster: Optional[str] = None,
    branch: Optional[str] = None,
    employee: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get upload entries with filtering
    Each customer upload appears as a separate entry
    """
    
    session = get_session()
    
    try:
        # Start with base query
        query = session.query(CustomerUploadEntry)
        
        # Apply date filtering
        if date_filter and date_filter != 'custom':
            start_utc, end_utc = get_date_range_utc(date_filter)
            query = query.filter(
                CustomerUploadEntry.upload_timestamp >= start_utc,
                CustomerUploadEntry.upload_timestamp <= end_utc
            )
        elif date_filter == 'custom' and (start_date or end_date):
            if start_date:
                start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                start_ist = IST.localize(start_dt)
                start_utc = start_ist.astimezone(pytz.UTC).replace(tzinfo=None)
                query = query.filter(CustomerUploadEntry.upload_timestamp >= start_utc)
            
            if end_date:
                end_dt = datetime.strptime(end_date, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
                end_ist = IST.localize(end_dt)
                end_utc = end_ist.astimezone(pytz.UTC).replace(tzinfo=None)
                query = query.filter(CustomerUploadEntry.upload_timestamp <= end_utc)
        
        # Apply search filtering
        if search:
            search_term = f"%{search.lower()}%"
            query = query.filter(
                (CustomerUploadEntry.full_name.ilike(search_term)) |
                (CustomerUploadEntry.primary_phone.ilike(search_term)) |
                (CustomerUploadEntry.loan_id.ilike(search_term))
            )
        
        # Apply other filters
        if state:
            query = query.filter(CustomerUploadEntry.state == state)
        if cluster:
            query = query.filter(CustomerUploadEntry.cluster == cluster)
        if branch:
            query = query.filter(CustomerUploadEntry.branch == branch)
        if employee:
            query = query.filter(CustomerUploadEntry.employee_name == employee)
        
        # Order by upload timestamp (newest first)
        query = query.order_by(CustomerUploadEntry.upload_timestamp.desc())
        
        # Execute query
        upload_entries = query.all()
        
        # Format results
        results = []
        for entry in upload_entries:
            entry_data = {
                "id": str(entry.id),
                "upload_timestamp": format_ist_datetime(entry.upload_timestamp),
                "file_upload_id": str(entry.file_upload_id),
                
                # Customer information
                "full_name": entry.full_name,
                "primary_phone": entry.primary_phone,
                "state": entry.state,
                "email": entry.email,
                "customer_fingerprint": entry.customer_fingerprint,
                
                # Loan information
                "loan_id": entry.loan_id,
                "principal_amount": float(entry.principal_amount or 0),
                "outstanding_amount": float(entry.outstanding_amount or 0),
                "due_amount": float(entry.due_amount or 0),
                "next_due_date": entry.next_due_date.strftime('%Y-%m-%d') if entry.next_due_date else None,
                "last_paid_date": entry.last_paid_date.strftime('%Y-%m-%d') if entry.last_paid_date else None,
                "last_paid_amount": float(entry.last_paid_amount or 0),
                
                # Branch and employee information
                "cluster": entry.cluster,
                "branch": entry.branch,
                "branch_contact_number": entry.branch_contact_number,
                "employee_name": entry.employee_name,
                "employee_id": entry.employee_id,
                "employee_contact_number": entry.employee_contact_number,
                
                # Metadata
                "is_new_customer": entry.is_new_customer,
                "is_new_loan": entry.is_new_loan,
                "processing_status": entry.processing_status,
                "created_at": format_ist_datetime(entry.created_at),
                "updated_at": format_ist_datetime(entry.updated_at)
            }
            results.append(entry_data)
        
        # Get summary statistics
        total_entries = len(results)
        new_customers = sum(1 for entry in upload_entries if entry.is_new_customer)
        new_loans = sum(1 for entry in upload_entries if entry.is_new_loan)
        unique_customers = len(set(entry.customer_fingerprint for entry in upload_entries))
        
        return {
            "success": True,
            "total_entries": total_entries,
            "unique_customers": unique_customers,
            "new_customers": new_customers,
            "new_loans": new_loans,
            "date_filter": date_filter,
            "start_date": start_date,
            "end_date": end_date,
            "entries": results
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching upload entries: {str(e)}")
    finally:
        session.close()

async def get_upload_statistics(date_filter: Optional[str] = None) -> Dict[str, Any]:
    """Get statistics about upload entries"""
    
    session = get_session()
    
    try:
        # Base query
        query = session.query(CustomerUploadEntry)
        
        # Apply date filtering
        if date_filter and date_filter != 'custom':
            start_utc, end_utc = get_date_range_utc(date_filter)
            query = query.filter(
                CustomerUploadEntry.upload_timestamp >= start_utc,
                CustomerUploadEntry.upload_timestamp <= end_utc
            )
        
        upload_entries = query.all()
        
        # Calculate statistics
        total_entries = len(upload_entries)
        unique_customers = len(set(entry.customer_fingerprint for entry in upload_entries))
        new_customers = sum(1 for entry in upload_entries if entry.is_new_customer)
        new_loans = sum(1 for entry in upload_entries if entry.is_new_loan)
        total_outstanding = sum(entry.outstanding_amount or 0 for entry in upload_entries)
        total_due = sum(entry.due_amount or 0 for entry in upload_entries)
        
        # Group by upload date
        daily_counts = {}
        for entry in upload_entries:
            upload_date = entry.upload_timestamp.replace(tzinfo=pytz.UTC).astimezone(IST).date()
            date_str = upload_date.strftime('%Y-%m-%d')
            if date_str not in daily_counts:
                daily_counts[date_str] = 0
            daily_counts[date_str] += 1
        
        return {
            "success": True,
            "total_entries": total_entries,
            "unique_customers": unique_customers,
            "new_customers": new_customers,
            "new_loans": new_loans,
            "total_outstanding": float(total_outstanding),
            "total_due": float(total_due),
            "daily_counts": daily_counts,
            "date_filter": date_filter
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching statistics: {str(e)}")
    finally:
        session.close()

# Example function to test the API
async def test_upload_entries_api():
    """Test the upload entries API"""
    
    print("🧪 Testing Upload Entries API")
    print("=" * 40)
    
    # Test different date filters
    filters = ['today', 'yesterday', 'this-week']
    
    for filter_name in filters:
        print(f"\n📅 Testing filter: {filter_name}")
        result = await get_upload_entries(date_filter=filter_name)
        print(f"Total entries: {result['total_entries']}")
        print(f"Unique customers: {result['unique_customers']}")
        print(f"New customers: {result['new_customers']}")
        
        if result['entries']:
            print("Sample entries:")
            for entry in result['entries'][:3]:  # Show first 3
                print(f"  - {entry['full_name']} ({entry['loan_id']}) - {entry['upload_timestamp']}")
    
    # Test statistics
    print(f"\n📊 Testing statistics")
    stats = await get_upload_statistics(date_filter='today')
    print(f"Statistics: {stats}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_upload_entries_api())
