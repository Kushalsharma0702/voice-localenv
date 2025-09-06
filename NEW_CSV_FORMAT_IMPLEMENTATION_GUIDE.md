# Enhanced CSV Upload System - Implementation Guide

## Overview
Your voice assistant application has been successfully updated to support the new CSV format with enhanced customer and loan data management. This document outlines all the changes made and how to use the new system.

## New CSV Format Support

### Supported CSV Columns
The system now processes CSV files with the following columns:
```
name,phone,loan_id,amount,due_date,state,Cluster,Branch,Branch Contact Number,Employee,Employee ID,Employee Contact Number,Last Paid Date,Last Paid Amount,Due Amount
```

### Column Mapping
- **name** → Customer full name
- **phone** → Customer primary phone (auto-normalized to +91 format)
- **loan_id** → Unique loan identifier
- **amount** → Outstanding loan amount
- **due_date** → Next payment due date
- **state** → Customer's state/region
- **Cluster** → Business cluster assignment
- **Branch** → Branch name
- **Branch Contact Number** → Branch phone number
- **Employee** → Assigned employee name
- **Employee ID** → Employee identifier
- **Employee Contact Number** → Employee phone number
- **Last Paid Date** → Date of last payment
- **Last Paid Amount** → Amount of last payment
- **Due Amount** → Current amount due

## Database Schema Updates

### Customer Table Enhancements
Added new column:
- `state` VARCHAR(100) - Customer's state/region

### Loan Table Enhancements
Added new columns:
- `due_amount` NUMERIC(15,2) - Current due amount
- `last_paid_date` DATE - Last payment date
- `last_paid_amount` NUMERIC(15,2) - Last payment amount
- `cluster` VARCHAR(100) - Business cluster
- `branch` VARCHAR(255) - Branch name
- `branch_contact_number` VARCHAR(20) - Branch phone
- `employee_name` VARCHAR(255) - Assigned employee
- `employee_id` VARCHAR(100) - Employee identifier
- `employee_contact_number` VARCHAR(20) - Employee phone

### New Indexes
Created performance indexes for:
- Customer state
- Loan cluster, branch, employee ID
- Last paid date and due amount

## Updated Components

### 1. Database Migration
✅ **File**: `migrate_new_csv_columns.py`
- Automatically adds new columns to existing database
- Creates performance indexes
- Includes verification step

### 2. Enhanced Schemas
✅ **File**: `database/schemas.py`
- Updated Customer and Loan models
- Added new column definitions
- Updated relationships and constraints

### 3. CSV Processing Service
✅ **File**: `services/enhanced_csv_processor.py`
- Parses new CSV format
- Handles data validation and normalization
- Provides deduplication logic
- Maps CSV data to database fields

### 4. Upload Service
✅ **File**: `services/enhanced_csv_upload_service.py`
- Orchestrates the complete upload process
- Provides progress tracking via WebSocket
- Handles error reporting and recovery

### 5. API Endpoints
✅ **Updated**: `/api/upload-customers`
- Now processes new CSV format
- Returns detailed processing results

✅ **Updated**: `/api/customers`
- Returns customer data with new fields
- Includes loan aggregation data
- Provides branch and employee information

### 6. Frontend Dashboard
✅ **File**: `static/enhanced_banking_dashboard.html`
- Already includes columns for new fields
- Displays state, branch, employee information
- Shows aggregated loan data

## Usage Instructions

### 1. Upload CSV File
1. Prepare your CSV file with the new format
2. Access the dashboard at your application URL
3. Use the file upload section
4. Select your CSV file and upload
5. Monitor progress in real-time

### 2. View Processing Results
The upload will return:
```json
{
  "success": true,
  "upload_id": "uuid",
  "processing_results": {
    "total_records": 100,
    "success_records": 95,
    "failed_records": 5,
    "new_customers": 30,
    "updated_customers": 65,
    "new_loans": 35,
    "updated_loans": 60
  }
}
```

### 3. Customer Data Access
Use the `/api/customers` endpoint to retrieve:
- Customer information with state
- Loan details with branch/employee data
- Payment history and due amounts
- Aggregated statistics

## Sample CSV File

A sample CSV file (`sample_new_format.csv`) has been created with the correct format:

```csv
name,phone,loan_id,amount,due_date,state,Cluster,Branch,Branch Contact Number,Employee,Employee ID,Employee Contact Number,Last Paid Date,Last Paid Amount,Due Amount
Rajesh Kumar,9876543210,LOAN001,250000,2024-01-15,Karnataka,South Cluster,Bangalore Main Branch,080-12345678,Priya Sharma,EMP001,9876543211,2023-12-10,5000,15000
```

## Data Processing Features

### Smart Deduplication
- Prevents duplicate customers based on phone + name fingerprint
- Updates existing records with new information
- Maintains data integrity across uploads

### Phone Number Normalization
- Automatically converts to +91 format for Indian numbers
- Handles various input formats (10-digit, 12-digit, etc.)
- Ensures consistent storage and matching

### Data Validation
- Validates date formats (multiple formats supported)
- Parses monetary amounts (handles currency symbols)
- Validates required fields

### Error Handling
- Detailed error reporting for failed records
- Continues processing despite individual record failures
- Provides line-by-line error information

## Migration Steps

### 1. Run Database Migration
```bash
python migrate_new_csv_columns.py
```

### 2. Test with Sample Data
```bash
# Upload the sample CSV file through the dashboard
# Verify data appears correctly in the customer list
```

### 3. Production Deployment
- Deploy updated code
- Run migration script
- Test with small batch first
- Monitor logs for any issues

## Monitoring and Troubleshooting

### Log Files
Check these log files for processing details:
- `logs/application.log` - General application logs
- `logs/database.log` - Database operations
- `logs/errors.log` - Error details

### Common Issues
1. **CSV Format Errors**: Ensure column headers match exactly
2. **Phone Number Issues**: Check format and country code
3. **Date Format Problems**: Use YYYY-MM-DD format for best results
4. **Memory Issues**: Process large files in smaller batches

## Next Steps

### Recommended Enhancements
1. **Batch Processing**: Add support for very large CSV files
2. **Data Export**: Create export functionality for processed data
3. **Analytics Dashboard**: Add reporting on branch/employee performance
4. **Audit Trail**: Track all changes with timestamps and user info

### Integration Points
1. **Call Campaigns**: Create campaigns based on branch/cluster
2. **Employee Assignment**: Route calls based on employee data
3. **Regional Analysis**: Analyze performance by state/branch
4. **Payment Tracking**: Monitor payment patterns and due amounts

## API Documentation

### POST /api/upload-customers
Upload and process CSV file
- **Body**: Multipart form with CSV file
- **Response**: Processing results with statistics

### GET /api/customers
Retrieve customer list with enhanced data
- **Response**: Array of customers with loan details

## Support
For any issues or questions:
1. Check the log files first
2. Verify CSV format matches specification
3. Ensure database migration completed successfully
4. Test with the provided sample CSV file

---
**Implementation Date**: September 5, 2025  
**Status**: ✅ Complete and Ready for Production
