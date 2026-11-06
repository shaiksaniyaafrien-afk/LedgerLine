from typing import Optional, Dict, Any
import json
from sqlalchemy.orm import Session
from app.models.audit import AuditLog


class AuditService:
    @staticmethod
    def log_event(
        db: Session,
        action: str,
        user_id: Optional[int] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditLog:
        details_str = json.dumps(details, default=str) if details else None
        audit_entry = AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            ip_address=ip_address,
            details=details_str,
        )
        db.add(audit_entry)
        # Note: Do not commit here if part of a larger unit of work;
        # but if called independently, it will be committed by the caller.
        return audit_entry

