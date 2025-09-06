"""
=============================================================================
VOICE ASSISTANT CALL MANAGEMENT SYSTEM - DATABASE SCHEMA DESIGN
=============================================================================

This file contains the comprehensive database schema design for the Voice 
Assistant Call Management System. It includes all tables, relationships, 
indexes, and constraints needed for a production-ready system.

Author: Voice Assistant Development Team
Created: August 31, 2025
Version: 2.0
=============================================================================
"""

from sqlalchemy import (
    create_engine, Column, String, DateTime, Text, JSON, Boolean, Integer, 
    ForeignKey, Index, UniqueConstraint, CheckConstraint, Numeric, Enum as SQLEnum
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.sql import func
from datetime import datetime
import uuid
import enum
from typing import Optional, List, Dict, Any

# =============================================================================
# BASE CONFIGURATION
# =============================================================================

Base = declarative_base()

# =============================================================================
# ENUMS FOR TYPE SAFETY
# =============================================================================

class CallStatus(enum.Enum):
    """Call status enumeration"""
    INITIATED = "initiated"
    RINGING = "ringing" 
    IN_PROGRESS = "in_progress"
    AGENT_TRANSFER = "agent_transfer"
    COMPLETED = "completed"
    FAILED = "failed"
    NOT_PICKED = "not_picked"
    CANCELLED = "cancelled"
    BUSY = "busy"

class CallDirection(enum.Enum):
    """Call direction enumeration"""
    INBOUND = "inbound"
    OUTBOUND = "outbound"

class CustomerStatus(enum.Enum):
    """Customer account status"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    BLOCKED = "blocked"
    PENDING = "pending"

class LoanStatus(enum.Enum):
    """Loan status enumeration"""
    ACTIVE = "active"
    OVERDUE = "overdue"
    PAID = "paid"
    DEFAULTED = "defaulted"
    RESTRUCTURED = "restructured"

class PaymentStatus(enum.Enum):
    """Payment status enumeration"""
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"

class FileUploadStatus(enum.Enum):
    """File upload status enumeration"""
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"

class ConversationSentiment(enum.Enum):
    """Conversation sentiment analysis"""
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    FRUSTRATED = "frustrated"
    SATISFIED = "satisfied"

# =============================================================================
# CORE CUSTOMER MANAGEMENT TABLES
# =============================================================================

class Customer(Base):
    """
    Customer information table
    Stores all customer demographic and contact information
    """
    __tablename__ = 'customers'
    
    # Primary identification
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_code = Column(String(50), unique=True, nullable=False, index=True)
    
    # Personal information
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100))
    full_name = Column(String(255), nullable=False, index=True)
    date_of_birth = Column(DateTime)
    gender = Column(String(10))
    
    # Contact information
    primary_phone = Column(String(20), nullable=False, unique=True, index=True)
    secondary_phone = Column(String(20))
    email = Column(String(255), index=True)
    
    # Address information
    address_line1 = Column(String(255))
    address_line2 = Column(String(255))
    city = Column(String(100))
    state = Column(String(100))
    postal_code = Column(String(20))
    country = Column(String(100), default='India')
    
    # Preferences
    preferred_language = Column(String(10), default='hi-IN')
    preferred_contact_time = Column(String(50))  # morning, afternoon, evening
    timezone = Column(String(50), default='Asia/Kolkata')
    
    # Account status
    status = Column(SQLEnum(CustomerStatus), default=CustomerStatus.ACTIVE)
    kyc_verified = Column(Boolean, default=False)
    consent_given = Column(Boolean, default=False)
    do_not_call = Column(Boolean, default=False)
    
    # Metadata
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    created_by = Column(String(100))
    last_contact_date = Column(DateTime)
    
    # Relationships
    loans = relationship("Loan", back_populates="customer", cascade="all, delete-orphan")
    call_sessions = relationship("CallSession", back_populates="customer")
    payments = relationship("Payment", back_populates="customer")
    customer_notes = relationship("CustomerNote", back_populates="customer", cascade="all, delete-orphan")
    
    # Indexes and constraints
    __table_args__ = (
        Index('idx_customer_phone', 'primary_phone'),
        Index('idx_customer_name', 'full_name'),
        Index('idx_customer_status', 'status'),
        Index('idx_customer_created', 'created_at'),
    )

class CustomerNote(Base):
    """
    Customer notes and comments
    Stores agent notes, customer feedback, and important observations
    """
    __tablename__ = 'customer_notes'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(UUID(as_uuid=True), ForeignKey('customers.id'), nullable=False)
    
    note_type = Column(String(50), nullable=False)  # agent_note, complaint, feedback, escalation
    title = Column(String(255))
    content = Column(Text, nullable=False)
    priority = Column(String(20), default='normal')  # low, normal, high, urgent
    
    created_at = Column(DateTime, default=func.now(), nullable=False)
    created_by = Column(String(100))
    
    # Relationships
    customer = relationship("Customer", back_populates="customer_notes")
    
    # Indexes
    __table_args__ = (
        Index('idx_customer_notes_customer', 'customer_id'),
        Index('idx_customer_notes_type', 'note_type'),
        Index('idx_customer_notes_created', 'created_at'),
    )

# =============================================================================
# LOAN MANAGEMENT TABLES
# =============================================================================

class Loan(Base):
    """
    Loan information table
    Stores all loan details, amounts, and terms
    """
    __tablename__ = 'loans'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(UUID(as_uuid=True), ForeignKey('customers.id'), nullable=False)
    
    # Loan identification
    loan_id = Column(String(50), unique=True, nullable=False, index=True)
    loan_type = Column(String(50))  # personal, home, auto, business
    
    # Financial details
    principal_amount = Column(Numeric(15, 2), nullable=False)
    outstanding_amount = Column(Numeric(15, 2), nullable=False)
    interest_rate = Column(Numeric(5, 2))
    
    # Term details
    loan_term_months = Column(Integer)
    emi_amount = Column(Numeric(10, 2))
    next_due_date = Column(DateTime)
    last_payment_date = Column(DateTime)
    
    # Status and dates
    status = Column(SQLEnum(LoanStatus), default=LoanStatus.ACTIVE)
    disbursement_date = Column(DateTime)
    maturity_date = Column(DateTime)
    
    # Risk assessment
    days_past_due = Column(Integer, default=0)
    risk_category = Column(String(20))  # low, medium, high
    
    # Metadata
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    customer = relationship("Customer", back_populates="loans")
    payments = relationship("Payment", back_populates="loan")
    
    # Indexes
    __table_args__ = (
        Index('idx_loan_customer', 'customer_id'),
        Index('idx_loan_status', 'status'),
        Index('idx_loan_due_date', 'next_due_date'),
        Index('idx_loan_risk', 'risk_category'),
    )

class Payment(Base):
    """
    Payment history table
    Tracks all customer payments and transactions
    """
    __tablename__ = 'payments'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(UUID(as_uuid=True), ForeignKey('customers.id'), nullable=False)
    loan_id = Column(UUID(as_uuid=True), ForeignKey('loans.id'), nullable=False)
    
    # Payment details
    payment_id = Column(String(100), unique=True, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    payment_method = Column(String(50))  # bank_transfer, upi, cash, cheque, online
    payment_date = Column(DateTime, nullable=False)
    
    # Status and processing
    status = Column(SQLEnum(PaymentStatus), default=PaymentStatus.PENDING)
    transaction_reference = Column(String(255))
    gateway_response = Column(JSON)
    
    # Metadata
    created_at = Column(DateTime, default=func.now(), nullable=False)
    processed_at = Column(DateTime)
    processed_by = Column(String(100))
    
    # Relationships
    customer = relationship("Customer", back_populates="payments")
    loan = relationship("Loan", back_populates="payments")
    
    # Indexes
    __table_args__ = (
        Index('idx_payment_customer', 'customer_id'),
        Index('idx_payment_loan', 'loan_id'),
        Index('idx_payment_date', 'payment_date'),
        Index('idx_payment_status', 'status'),
    )

# =============================================================================
# CALL MANAGEMENT TABLES
# =============================================================================

class CallSession(Base):
    """
    Call session management table
    Tracks all call interactions with customers
    """
    __tablename__ = 'call_sessions'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(UUID(as_uuid=True), ForeignKey('customers.id'), nullable=False)
    
    # Call identification
    call_sid = Column(String(100), unique=True, nullable=False, index=True)
    websocket_session_id = Column(String(100), index=True)
    
    # Call details
    direction = Column(SQLEnum(CallDirection), nullable=False)
    status = Column(SQLEnum(CallStatus), default=CallStatus.INITIATED)
    
    # Timing information
    initiated_at = Column(DateTime, default=func.now(), nullable=False)
    answered_at = Column(DateTime)
    ended_at = Column(DateTime)
    duration_seconds = Column(Integer)
    
    # Numbers involved
    from_number = Column(String(20))
    to_number = Column(String(20))
    caller_id = Column(String(20))
    
    # Agent transfer details
    agent_transfer_initiated = Column(Boolean, default=False)
    agent_transfer_time = Column(DateTime)
    agent_number = Column(String(20))
    agent_connected = Column(Boolean, default=False)
    
    # AI and conversation data
    language_detected = Column(String(10))
    intent_detected = Column(String(100))
    sentiment_score = Column(Numeric(3, 2))  # -1 to +1
    conversation_summary = Column(Text)
    
    # Exotel specific data
    exotel_data = Column(JSON)
    recording_url = Column(String(500))
    
    # Quality metrics
    call_quality_rating = Column(Integer)  # 1-5 rating
    technical_issues = Column(Boolean, default=False)
    
    # Metadata
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    customer = relationship("Customer", back_populates="call_sessions")
    status_updates = relationship("CallStatusUpdate", back_populates="call_session", cascade="all, delete-orphan")
    conversation_logs = relationship("ConversationLog", back_populates="call_session", cascade="all, delete-orphan")
    call_analytics = relationship("CallAnalytics", back_populates="call_session", uselist=False, cascade="all, delete-orphan")
    
    # Indexes
    __table_args__ = (
        Index('idx_call_customer', 'customer_id'),
        Index('idx_call_status', 'status'),
        Index('idx_call_initiated', 'initiated_at'),
        Index('idx_call_sid', 'call_sid'),
        Index('idx_call_direction', 'direction'),
    )

class CallStatusUpdate(Base):
    """
    Call status tracking table
    Records all status changes during a call
    """
    __tablename__ = 'call_status_updates'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    call_session_id = Column(UUID(as_uuid=True), ForeignKey('call_sessions.id'), nullable=False)
    
    # Status information
    from_status = Column(SQLEnum(CallStatus))
    to_status = Column(SQLEnum(CallStatus), nullable=False)
    status_message = Column(Text)
    
    # Metadata
    timestamp = Column(DateTime, default=func.now(), nullable=False)
    extra_data = Column(JSON)
    triggered_by = Column(String(100))  # system, agent, customer
    
    # Relationships
    call_session = relationship("CallSession", back_populates="status_updates")
    
    # Indexes
    __table_args__ = (
        Index('idx_status_call', 'call_session_id'),
        Index('idx_status_timestamp', 'timestamp'),
        Index('idx_status_to', 'to_status'),
    )

class ConversationLog(Base):
    """
    Conversation transcript table
    Stores detailed conversation logs and AI interactions
    """
    __tablename__ = 'conversation_logs'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    call_session_id = Column(UUID(as_uuid=True), ForeignKey('call_sessions.id'), nullable=False)
    
    # Message details
    sequence_number = Column(Integer, nullable=False)
    speaker = Column(String(20), nullable=False)  # customer, ai, agent, system
    message_type = Column(String(30))  # speech, text, system_message, transfer
    
    # Content
    original_text = Column(Text)
    translated_text = Column(Text)
    language_code = Column(String(10))
    confidence_score = Column(Numeric(3, 2))
    
    # AI processing
    intent = Column(String(100))
    entities = Column(JSON)
    sentiment = Column(SQLEnum(ConversationSentiment))
    
    # Audio details
    audio_duration = Column(Numeric(5, 2))
    audio_file_path = Column(String(500))
    
    # Timing
    timestamp = Column(DateTime, default=func.now(), nullable=False)
    
    # Relationships
    call_session = relationship("CallSession", back_populates="conversation_logs")
    
    # Indexes
    __table_args__ = (
        Index('idx_conversation_call', 'call_session_id'),
        Index('idx_conversation_sequence', 'call_session_id', 'sequence_number'),
        Index('idx_conversation_timestamp', 'timestamp'),
        Index('idx_conversation_speaker', 'speaker'),
    )

class CallAnalytics(Base):
    """
    Call analytics and insights table
    Stores aggregated analytics and AI insights for each call
    """
    __tablename__ = 'call_analytics'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    call_session_id = Column(UUID(as_uuid=True), ForeignKey('call_sessions.id'), nullable=False)
    
    # Conversation metrics
    total_messages = Column(Integer, default=0)
    customer_messages = Column(Integer, default=0)
    ai_messages = Column(Integer, default=0)
    average_response_time = Column(Numeric(5, 2))
    
    # Sentiment analysis
    overall_sentiment = Column(SQLEnum(ConversationSentiment))
    sentiment_trend = Column(String(20))  # improving, declining, stable
    frustration_incidents = Column(Integer, default=0)
    
    # Language and understanding
    languages_detected = Column(ARRAY(String(10)))
    primary_language = Column(String(10))
    language_switches = Column(Integer, default=0)
    avg_confidence_score = Column(Numeric(3, 2))
    
    # Intent analysis
    primary_intent = Column(String(100))
    intent_changes = Column(Integer, default=0)
    resolution_achieved = Column(Boolean)
    
    # Quality metrics
    call_effectiveness_score = Column(Numeric(3, 2))  # 0-1 scale
    customer_satisfaction_predicted = Column(Numeric(3, 2))
    
    # Technical metrics
    audio_quality_score = Column(Numeric(3, 2))
    connection_issues = Column(Integer, default=0)
    silence_periods = Column(Integer, default=0)
    
    # Outcomes
    escalation_required = Column(Boolean, default=False)
    follow_up_needed = Column(Boolean, default=False)
    payment_commitment = Column(Boolean, default=False)
    
    # Metadata
    analyzed_at = Column(DateTime, default=func.now(), nullable=False)
    ai_model_version = Column(String(50))
    
    # Relationships
    call_session = relationship("CallSession", back_populates="call_analytics")
    
    # Indexes
    __table_args__ = (
        Index('idx_analytics_call', 'call_session_id'),
        Index('idx_analytics_sentiment', 'overall_sentiment'),
        Index('idx_analytics_effectiveness', 'call_effectiveness_score'),
        Index('idx_analytics_analyzed', 'analyzed_at'),
    )

# =============================================================================
# SYSTEM MANAGEMENT TABLES
# =============================================================================

class FileUpload(Base):
    """
    File upload tracking table
    Manages bulk data uploads and processing status
    """
    __tablename__ = 'file_uploads'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # File details
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer)
    file_type = Column(String(50))
    
    # Processing status
    status = Column(SQLEnum(FileUploadStatus), default=FileUploadStatus.PROCESSING)
    total_records = Column(Integer, default=0)
    processed_records = Column(Integer, default=0)
    success_records = Column(Integer, default=0)
    failed_records = Column(Integer, default=0)
    
    # Processing details
    processing_started_at = Column(DateTime)
    processing_completed_at = Column(DateTime)
    processing_errors = Column(JSON)
    validation_errors = Column(JSON)
    
    # Metadata
    uploaded_at = Column(DateTime, default=func.now(), nullable=False)
    uploaded_by = Column(String(100), nullable=False)
    upload_batch_id = Column(String(100))
    
    # Indexes
    __table_args__ = (
        Index('idx_upload_status', 'status'),
        Index('idx_upload_date', 'uploaded_at'),
        Index('idx_upload_batch', 'upload_batch_id'),
        Index('idx_upload_user', 'uploaded_by'),
    )

class SystemConfiguration(Base):
    """
    System configuration table
    Stores application settings and configuration values
    """
    __tablename__ = 'system_configuration'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Configuration details
    config_key = Column(String(100), unique=True, nullable=False)
    config_value = Column(Text)
    config_type = Column(String(30))  # string, integer, boolean, json
    description = Column(Text)
    
    # Management
    is_active = Column(Boolean, default=True)
    is_system = Column(Boolean, default=False)  # True for system-managed configs
    
    # Metadata
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    updated_by = Column(String(100))
    
    # Indexes
    __table_args__ = (
        Index('idx_config_key', 'config_key'),
        Index('idx_config_active', 'is_active'),
    )

class AuditLog(Base):
    """
    Audit log table
    Tracks all important system events and changes
    """
    __tablename__ = 'audit_logs'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Event details
    event_type = Column(String(50), nullable=False)  # create, update, delete, call, payment
    table_name = Column(String(50))
    record_id = Column(String(100))
    
    # Change details
    old_values = Column(JSON)
    new_values = Column(JSON)
    changes_summary = Column(Text)
    
    # Context
    user_id = Column(String(100))
    session_id = Column(String(100))
    ip_address = Column(String(45))
    user_agent = Column(Text)
    
    # Metadata
    timestamp = Column(DateTime, default=func.now(), nullable=False)
    
    # Indexes
    __table_args__ = (
        Index('idx_audit_event', 'event_type'),
        Index('idx_audit_table', 'table_name'),
        Index('idx_audit_timestamp', 'timestamp'),
        Index('idx_audit_user', 'user_id'),
    )

# =============================================================================
# PERFORMANCE MONITORING TABLES
# =============================================================================

class SystemMetrics(Base):
    """
    System performance metrics table
    Tracks application performance and usage statistics
    """
    __tablename__ = 'system_metrics'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Metric details
    metric_name = Column(String(100), nullable=False)
    metric_value = Column(Numeric(15, 4), nullable=False)
    metric_unit = Column(String(20))
    metric_category = Column(String(50))  # performance, usage, business
    
    # Context
    additional_data = Column(JSON)
    
    # Timing
    recorded_at = Column(DateTime, default=func.now(), nullable=False)
    
    # Indexes
    __table_args__ = (
        Index('idx_metrics_name', 'metric_name'),
        Index('idx_metrics_category', 'metric_category'),
        Index('idx_metrics_recorded', 'recorded_at'),
        Index('idx_metrics_name_time', 'metric_name', 'recorded_at'),
    )

# =============================================================================
# VIEWS AND MATERIALIZED VIEWS (Future Implementation)
# =============================================================================

"""
Note: The following views can be created using raw SQL in migration scripts:

1. customer_summary_view - Aggregated customer data with loan and call statistics
2. daily_call_metrics_view - Daily aggregated call metrics
3. agent_performance_view - Agent performance statistics
4. collection_efficiency_view - Collection efficiency metrics
5. customer_risk_view - Customer risk assessment data

Example view creation:
CREATE MATERIALIZED VIEW customer_summary_view AS
SELECT 
    c.id,
    c.full_name,
    c.primary_phone,
    COUNT(DISTINCT l.id) as total_loans,
    SUM(l.outstanding_amount) as total_outstanding,
    COUNT(DISTINCT cs.id) as total_calls,
    MAX(cs.initiated_at) as last_call_date,
    AVG(ca.call_effectiveness_score) as avg_call_effectiveness
FROM customers c
LEFT JOIN loans l ON c.id = l.customer_id
LEFT JOIN call_sessions cs ON c.id = cs.customer_id
LEFT JOIN call_analytics ca ON cs.id = ca.call_session_id
GROUP BY c.id, c.full_name, c.primary_phone;
"""

# =============================================================================
# DATABASE CONSTRAINTS AND BUSINESS RULES
# =============================================================================

"""
Additional constraints to be added:

1. Customer phone number format validation
2. Loan amount positive check
3. Call duration positive check
4. Payment amount positive check
5. Date consistency checks (end_date > start_date)
6. Status transition validation
7. Foreign key cascade rules
8. Unique constraint combinations

Example constraint:
ALTER TABLE loans ADD CONSTRAINT chk_loan_amount_positive 
CHECK (principal_amount > 0 AND outstanding_amount >= 0);

ALTER TABLE call_sessions ADD CONSTRAINT chk_call_duration_positive 
CHECK (duration_seconds >= 0);

ALTER TABLE payments ADD CONSTRAINT chk_payment_amount_positive 
CHECK (amount > 0);
"""

# =============================================================================
# INDEXES FOR PERFORMANCE OPTIMIZATION
# =============================================================================

"""
Additional indexes to be created:

1. Composite indexes for common query patterns
2. Partial indexes for filtered queries
3. Expression indexes for computed columns
4. Text search indexes for full-text search

Example indexes:
CREATE INDEX idx_customers_active_phone ON customers (primary_phone) 
WHERE status = 'active';

CREATE INDEX idx_loans_overdue ON loans (customer_id, next_due_date) 
WHERE status = 'overdue';

CREATE INDEX idx_calls_recent ON call_sessions (customer_id, initiated_at DESC) 
WHERE initiated_at > NOW() - INTERVAL '30 days';
"""

# =============================================================================
# END OF SCHEMA DESIGN
# =============================================================================
