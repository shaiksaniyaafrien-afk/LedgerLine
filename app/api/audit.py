from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_auditor
from app.models.user import User
from app.models.audit import AuditLog
from app.models.ledger import LedgerEntry
from app.schemas.audit import (
    AuditLogResponse,
    SystemReconciliationResponse,
    TamperProofReportResponse,
)
from app.services.ledger_service import LedgerService

router = APIRouter(prefix="/api/audit", tags=["Audit & Verification"])


@router.get("/reconciliation", response_model=SystemReconciliationResponse)
def get_system_reconciliation(
    current_user: User = Depends(require_auditor),
    db: Session = Depends(get_db),
):
    """
    Auditor and Admin endpoint:
    Verifies that the books balance mathematically.
    Invariant: Sum(Customer Balances) == Sum(Deposits) - Sum(Withdrawals)
    Invariant: Internal Transfers net to zero.
    Invariant: Sum(Credits) == Sum(Debits) across double-entry ledger.
    """
    return LedgerService.get_system_reconciliation(db)


@router.get("/tamper-check", response_model=TamperProofReportResponse)
def run_tamper_verification(
    current_user: User = Depends(require_auditor),
    db: Session = Depends(get_db),
):
    """
    Auditor and Admin endpoint:
    Verifies cryptographic SHA-256 hash chains across all account ledgers.
    Proves that no record has been inserted, altered, or deleted out of order.
    """
    return LedgerService.verify_system_tamper_proof(db)


@router.get("/logs", response_model=List[AuditLogResponse])
def get_audit_logs(
    limit: int = Query(50, ge=1, le=500),
    action: Optional[str] = None,
    current_user: User = Depends(require_auditor),
    db: Session = Depends(get_db),
):
    """
    Auditor and Admin endpoint:
    Returns the immutable audit trail of actions taken in the system.
    """
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    logs = query.order_by(AuditLog.id.desc()).limit(limit).all()

    # Populate usernames for response
    result = []
    for log in logs:
        user_name = log.user.username if log.user else "System/Anonymous"
        result.append(
            AuditLogResponse(
                id=log.id,
                user_id=log.user_id,
                username=user_name,
                action=log.action,
                entity_type=log.entity_type,
                entity_id=log.entity_id,
                ip_address=log.ip_address,
                details=log.details,
                created_at=log.created_at,
            )
        )
    return result

