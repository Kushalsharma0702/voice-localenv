# 📊 Voice Assistant Application - Complete Data Flow Guide

## 🎯 Overview
This document explains how data flows through your voice assistant application from CSV upload to call completion, showing the purpose of each table and how data moves between them.

## 🗄️ Database Schema Overview

### Core Tables (Main Data Entities)
```
📋 customers        → Root entity for customer information
💰 loans           → Loan details linked to customers  
📞 call_sessions   → Individual call tracking
📊 call_status_updates → Call status history
```

### Upload Processing Tables  
```
📁 file_uploads    → CSV batch upload tracking
📄 upload_rows     → Individual CSV row processing
```

## 🔄 Complete Data Flow Process

### STEP 1: CSV Upload Processing
```
User uploads CSV file
        ↓
📁 file_uploads table
   - Records the upload batch
   - Tracks: filename, uploaded_by, total_records
   - Status: 'processing' → 'completed'/'failed'
        ↓
📄 upload_rows table  
   - Each CSV row becomes one record
   - Stores: raw_data (JSON), line_number, row_fingerprint
   - Links to file_uploads via file_upload_id
```

**CSV Format Supported:**
```csv
name,phone,loan_id,amount,due_date,state,Cluster,Branch,Branch Contact Number,Employee,Employee ID,Employee Contact Number,Last Paid Date,Last Paid Amount,Due Amount
```

### STEP 2: Data Processing & Deduplication
```
For each upload_row:
        ↓
🔍 Customer Matching Process
   - Generate fingerprint from phone + name
   - Check if customer exists in 📋 customers table
   - If exists: Update existing record
   - If new: Create new customer record
        ↓
📋 customers table
   - Stores: full_name, primary_phone, state, email
   - Tracks: first_uploaded_at, last_contact_date
   - Has unique fingerprint for deduplication
        ↓
🔍 Loan Matching Process  
   - Check if loan_id exists in 💰 loans table
   - If exists: Update loan details
   - If new: Create new loan record
        ↓
💰 loans table
   - Links to customer via customer_id (foreign key)
   - Stores: loan_id, outstanding_amount, due_amount
   - Branch info: cluster, branch, employee details
   - Payment info: last_paid_date, last_paid_amount
        ↓
📄 update upload_rows
   - Set match_customer_id → points to customers.id
   - Set match_loan_id → points to loans.id
   - Status: 'pending' → 'matched'/'created'
```

### STEP 3: Call Triggering Process
```
User triggers call for customer
        ↓
📞 call_sessions table
   - Creates new call record
   - Links: customer_id, loan_id (foreign keys)
   - Stores: to_number, from_number, call_sid
   - Tracks: triggered_by_batch, triggered_by_row
   - Initial status: 'scheduled'
        ↓
🎯 Exotel API Call
   - System calls Exotel API with customer phone
   - Receives call_sid from Exotel
   - Updates call_sessions.call_sid
        ↓
📊 call_status_updates table
   - Records every status change
   - Links to call_sessions via call_session_id
   - Timeline: 'initiated' → 'ringing' → 'in_progress' → 'completed'
```

### STEP 4: Call Status Tracking
```
Exotel webhook updates ↓
📊 call_status_updates
   - New record for each status change
   - Stores: status, message, timestamp, extra_data
        ↓
📞 call_sessions (updated)
   - Current status updated
   - Duration calculated when completed
   - Metadata stored (conversation details)
        ↓
📋 customers (updated)
   - last_contact_date updated
   - Call history maintained via relationships
```

## 🔗 Table Relationships & Foreign Keys

### Primary Relationships:
```
📋 customers (1) ←→ (many) 💰 loans
   - customers.id ← loans.customer_id

📋 customers (1) ←→ (many) 📞 call_sessions  
   - customers.id ← call_sessions.customer_id

💰 loans (1) ←→ (many) 📞 call_sessions
   - loans.id ← call_sessions.loan_id

📞 call_sessions (1) ←→ (many) 📊 call_status_updates
   - call_sessions.id ← call_status_updates.call_session_id

📁 file_uploads (1) ←→ (many) 📄 upload_rows
   - file_uploads.id ← upload_rows.file_upload_id
```

### Tracking Relationships:
```
📄 upload_rows → 📋 customers (via match_customer_id)
📄 upload_rows → 💰 loans (via match_loan_id)
📞 call_sessions → 📁 file_uploads (via triggered_by_batch)  
📞 call_sessions → 📄 upload_rows (via triggered_by_row)
```

## 📊 Data Examples

### Example: Single Customer Journey

**1. CSV Upload:**
```csv
Rajesh Kumar,9876543210,LOAN001,250000,2024-01-15,Karnataka,South Cluster,Bangalore Main Branch,080-12345678,Priya Sharma,EMP001,9876543211,2023-12-10,5000,15000
```

**2. Data Processing:**
```sql
-- file_uploads record
INSERT INTO file_uploads (filename, total_records, status) 
VALUES ('customer_data.csv', 1, 'processing');

-- upload_rows record  
INSERT INTO upload_rows (file_upload_id, line_number, raw_data, phone_normalized)
VALUES (uuid, 1, {csv_json_data}, '9876543210');

-- customers record (new or updated)
INSERT INTO customers (fingerprint, full_name, primary_phone, state)
VALUES ('abc123hash', 'Rajesh Kumar', '+919876543210', 'Karnataka');

-- loans record (new or updated)  
INSERT INTO loans (customer_id, loan_id, outstanding_amount, cluster, branch)
VALUES (customer_uuid, 'LOAN001', 250000, 'South Cluster', 'Bangalore Main Branch');

-- Update upload_rows with matches
UPDATE upload_rows SET match_customer_id = customer_uuid, match_loan_id = loan_uuid;
```

**3. Call Trigger:**
```sql
-- call_sessions record
INSERT INTO call_sessions (customer_id, loan_id, to_number, triggered_by_batch)
VALUES (customer_uuid, loan_uuid, '+919876543210', file_upload_uuid);

-- call_status_updates records (multiple as call progresses)
INSERT INTO call_status_updates (call_session_id, status, timestamp)
VALUES (call_uuid, 'initiated', now()),
       (call_uuid, 'ringing', now() + 5sec),
       (call_uuid, 'in_progress', now() + 10sec),
       (call_uuid, 'completed', now() + 120sec);
```

## 🔍 Key Features

### Deduplication Strategy:
- **Fingerprint-based**: Prevents duplicate customers using phone + name hash
- **Phone matching**: Secondary matching by normalized phone numbers  
- **Loan ID matching**: Prevents duplicate loans using external loan_id

### Audit Trail:
- **upload_rows**: Complete history of what was uploaded
- **call_status_updates**: Full call lifecycle tracking  
- **file_uploads**: Batch processing results and errors

### Data Integrity:
- **Foreign keys**: Ensure referential integrity
- **Unique constraints**: Prevent duplicates  
- **Cascade deletes**: Clean up related data when parent is deleted
- **Indexes**: Fast lookups on phone numbers, dates, statuses

### Performance Optimizations:
- **Indexes** on frequently queried fields (phone, status, dates)
- **JSON storage** for flexible metadata
- **Batch processing** for large CSV uploads
- **Connection pooling** for database efficiency

## 🎯 Dashboard Data Flow

### Frontend Display:
```
Dashboard loads ↓
API call: GET /api/customers
        ↓  
Query joins customers + loans + call_sessions
        ↓
Returns aggregated data:
   - Customer info from customers table
   - Loan totals from loans table  
   - Call status from latest call_sessions
   - Upload date from first_uploaded_at
        ↓
Frontend filters and displays:
   - Date filters (today, yesterday, week)
   - Status badges (ready, calling, completed)
   - CSV format table with all loan details
```

This comprehensive flow ensures complete traceability from CSV upload to call completion while maintaining data integrity and enabling efficient querying for the dashboard.
