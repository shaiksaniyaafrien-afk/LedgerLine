from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel


class AuditLogResponse(BaseModel):
    id: int
    user_id: Optional[int]
    username: Optional[str] = None
    action: str
    entity_type: Optional[str]
    entity_id: Optional[str]
    ip_address: Optional[str]
    details: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class SystemReconciliationResponse(BaseModel):
    is_balanced: bool
    total_customer_balances: Decimal
    total_external_deposits: Decimal
    total_external_withdrawals: Decimal
    expected_customer_balances: Decimal
    discrepancy: Decimal
    total_internal_transfers_volume: Decimal
    total_credits: Decimal
    total_debits: Decimal
    ledger_double_entry_balanced: bool
    total_accounts: int
    total_ledger_entries: int
    total_refused_attempts: int
    checked_at: datetime


class TamperVerificationEntry(BaseModel):
    account_id: int
    account_number: str
    is_valid: bool
    total_entries_verified: int
    corrupted_entry_id: Optional[int] = None
    error_message: Optional[str] = None


class TamperProofReportResponse(BaseModel):
    all_chains_valid: bool
    accounts_checked: int
    total_entries_checked: int
    details: List[TamperVerificationEntry]
    checked_at: datetime

