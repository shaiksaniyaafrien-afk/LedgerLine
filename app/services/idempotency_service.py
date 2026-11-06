import hashlib
import json
from typing import Optional, Tuple, Any, Dict
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.idempotency import IdempotencyRecord, IdempotencyStatus


class IdempotencyService:
    @staticmethod
    def generate_payload_hash(endpoint: str, payload: Dict[str, Any]) -> str:
        canonical_json = json.dumps(payload, sort_keys=True, default=str)
        content = f"{endpoint}:{canonical_json}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def check_or_create(
        db: Session,
        user_id: int,
        key: str,
        endpoint: str,
        payload: Dict[str, Any],
    ) -> Tuple[Optional[IdempotencyRecord], bool]:
        """
        Returns:
            (record, is_completed)
            - If is_completed is True: caller should return the cached response immediately.
            - If is_completed is False: caller is granted the lock and should proceed with execution.
        Raises:
            HTTPException 422: if key was reused with mismatched payload.
            HTTPException 409: if request with this key is currently in progress.
        """
        request_hash = IdempotencyService.generate_payload_hash(endpoint, payload)

        # Check existing record
        record = (
            db.query(IdempotencyRecord)
            .filter(
                IdempotencyRecord.key == key,
                IdempotencyRecord.user_id == user_id,
            )
            .first()
        )

        if record:
            if record.request_hash != request_hash:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Idempotency key collision: Same key was submitted with different request parameters.",
                )

            if record.status == IdempotencyStatus.PROCESSING:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A transaction with this idempotency key is currently processing. Please retry shortly.",
                )

            if record.status == IdempotencyStatus.COMPLETED:
                return record, True

            # If it was marked FAILED, allow re-trying
            record.status = IdempotencyStatus.PROCESSING
            record.request_hash = request_hash
            db.commit()
            return record, False

        # Create new processing record
        new_record = IdempotencyRecord(
            key=key,
            user_id=user_id,
            endpoint=endpoint,
            request_hash=request_hash,
            status=IdempotencyStatus.PROCESSING,
        )
        db.add(new_record)
        try:
            db.commit()
            db.refresh(new_record)
            return new_record, False
        except Exception:
            db.rollback()
            # If concurrent race inserted it simultaneously
            existing = (
                db.query(IdempotencyRecord)
                .filter(
                    IdempotencyRecord.key == key,
                    IdempotencyRecord.user_id == user_id,
                )
                .first()
            )
            if existing:
                if existing.status == IdempotencyStatus.COMPLETED:
                    return existing, True
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Concurrent request in flight for this idempotency key.",
                )
            raise

    @staticmethod
    def finalize(
        db: Session,
        key: str,
        user_id: int,
        response_code: int,
        response_data: Dict[str, Any],
    ) -> None:
        record = (
            db.query(IdempotencyRecord)
            .filter(
                IdempotencyRecord.key == key,
                IdempotencyRecord.user_id == user_id,
            )
            .first()
        )
        if record:
            record.status = IdempotencyStatus.COMPLETED
            record.response_code = response_code
            record.response_body = json.dumps(response_data, default=str)
            db.commit()

