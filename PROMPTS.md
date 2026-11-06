# LedgerLine — AI Directives & Engineering Log (`PROMPTS.md`)

This log documents prompt directives, generated outputs, critical security/architectural defects caught during review, and the engineering resolutions implemented.

---

### Entry 1 — Password Hashing & Authentication Vulnerability
* **Date**: 2026-11-06
* **Category**: Authentication & Access Control
* **What I asked for**:
  > "Implement secure password hashing and verification for user authentication in `app/core/security.py` using standard FastAPI patterns."
* **What the tool produced**:
  The AI generated a standard passlib configuration:
  ```python
  from passlib.context import CryptContext
  pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
  def hash_password(password: str): return pwd_context.hash(password)
  def verify_password(plain, hashed): return pwd_context.verify(plain, hashed)
  ```
* **What was wrong with it**:
  When tested under Python 3.13, this crashed during runtime with:
  `AttributeError: module 'bcrypt' has no attribute '__about__'` and `ValueError: password cannot be longer than 72 bytes`.
  `passlib` 1.7.4 is unmaintained and relies on private internal attributes of legacy bcrypt versions that were removed in bcrypt 4.1+. Relying on passlib would cause authentication failures and 500 Internal Server Errors in production.
* **What I did instead**:
  Discarded passlib and implemented direct, native `bcrypt` functions with explicit 72-byte truncation:
  ```python
  import bcrypt

  def hash_password(password: str) -> str:
      pwd_bytes = password.encode("utf-8")[:72]
      salt = bcrypt.gensalt(rounds=12)
      return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")

  def verify_password(plain_password: str, hashed_password: str) -> bool:
      pwd_bytes = plain_password.encode("utf-8")[:72]
      return bcrypt.checkpw(pwd_bytes, hashed_password.encode("utf-8"))
  ```
* **Associated Commit**: `feat(auth): implement resilient native bcrypt authentication`

---

### Entry 2 — Concurrency Overdraft & Naive Read-Check Race Condition
* **Date**: 2026-11-06
* **Category**: Concurrency & Money Integrity
* **What I asked for**:
  > "Write transaction logic for withdrawals and transfers that checks whether an account has sufficient funds before debiting."
* **What the tool produced**:
  The AI produced standard application-level read-then-write code:
  ```python
  account = db.query(Account).filter(Account.id == account_id).first()
  if account.balance < amount:
      raise HTTPException(400, "Insufficient funds")
  account.balance -= amount
  db.commit()
  ```
* **What was wrong with it**:
  This is vulnerable to race conditions under concurrent load (TOCTOU: Time-of-Check to Time-of-Use). When 10 concurrent requests arrive at the same millisecond to withdraw $100 from an account holding $200, all 10 read `balance == 200` before any transaction commits, resulting in all 10 succeeding and leaving the account at -$800!
* **What I did instead**:
  Implemented a three-layer defense:
  1. Deterministic row-level locking (`SELECT ... FOR UPDATE`) ordered by account ID to prevent deadlocks.
  2. Database-level atomic compare-and-swap conditional update using SQLAlchemy:
     ```python
     update_stmt = (
         update(Account)
         .where(Account.id == account.id, Account.balance >= amount)
         .values(balance=Account.balance - amount)
     )
     res = db.execute(update_stmt)
     if res.rowcount == 0:
         # Refuse transaction: balance was insufficient or already spent
         ...
     ```
  3. Enforced a hard database CHECK constraint: `CONSTRAINT chk_account_balance_non_negative CHECK (balance >= 0)`.
  Verified via multithreaded test `test_concurrent_withdrawals_cannot_overdraw`.
* **Associated Commit**: `fix(concurrency): enforce atomic compare-and-swap balance updates and row locking`

---

### Entry 3 — Missing Ledger Trail for Refused Attempts
* **Date**: 2026-11-06
* **Category**: Authorisation, Access Control & Audit Trail
* **What I asked for**:
  > "Handle failed transfer attempts (insufficient funds, unauthorized account access) by rolling back the transaction."
* **What the tool produced**:
  ```python
  except InsufficientFundsException:
      db.rollback()
      raise HTTPException(400, "Insufficient funds")
  ```
* **What was wrong with it**:
  Rolling back the database session erases all record of the refused event! The problem statement mandates: *"The ledger records every posting and every refused attempt... a per-account statement: every debit, every credit, and every refused attempt, each with the resulting running balance and who initiated it."*
  Erasing failed attempts destroys audit compliance, hides attempted unauthorized attacks, and prevents account holders from seeing why a transfer failed.
* **What I did instead**:
  Refactored the failure handler to explicitly record a `REFUSED` transaction and a `REFUSED` ledger entry before committing the audit record:
  ```python
  LedgerService.create_ledger_entry(
      db=db,
      account_id=account.id,
      transaction_id=refused_txn.id,
      entry_type=LedgerEntryType.REFUSED,
      amount=amount,
      running_balance=account.balance,  # Balance remains unchanged
      initiated_by_user_id=initiated_by_user_id,
      refusal_reason="INSUFFICIENT_FUNDS",
  )
  db.commit()
  ```
  This ensures that statements display failed attempts alongside debits and credits with zero balance alteration.
* **Associated Commit**: `feat(ledger): record append-only refused attempts in account statements`

---

### Entry 4 — Idempotency Key Replay Without Payload Integrity
* **Date**: 2026-11-06
* **Category**: Idempotency & Money Integrity
* **What I asked for**:
  > "Add an idempotency key mechanism so that replaying a transfer request returns the original result without executing twice."
* **What the tool produced**:
  The AI suggested checking if the key exists in an `IdempotencyRecord` table and returning the cached response if present.
* **What was wrong with it**:
  The suggested implementation only checked `key == key`. It failed to verify whether the incoming request payload matched the original request!
  If an adversary replayed an old key with a different recipient or higher amount, or if a client software bug accidentally reused a UUID, the server would return the old receipt while suppressing the new transfer!
* **What I did instead**:
  Built an idempotency service with canonical payload hashing:
  ```python
  request_hash = hashlib.sha256(f"{endpoint}:{canonical_json}".encode("utf-8")).hexdigest()
  if record and record.request_hash != request_hash:
      raise HTTPException(status_code=422, detail="Idempotency key collision with conflicting payload.")
  ```
  Additionally handled in-flight concurrency with `409 Conflict` status, and marked replay responses with `Idempotent-Replay: true` header and `is_duplicate: true`.
* **Associated Commit**: `feat(idempotency): add canonical payload hashing and in-flight conflict guards`

---

### Entry 5 — Hash Chain Deserialization Desync in Audit Verification
* **Date**: 2026-11-06
* **Category**: Audit Trail & Cryptographic Proof
* **What I asked for**:
  > "Create an auditor tool that validates cryptographic SHA-256 hash chains across ledger entries to prove tamper-evidence."
* **What the tool produced**:
  ```python
  # Insertion
  entry_hash = hashlib.sha256(f"{prev_hash}|{amount}|{now.isoformat()}".encode()).hexdigest()
  # Verification
  computed_hash = hashlib.sha256(f"{prev_hash}|{entry.amount}|{entry.created_at.isoformat()}".encode()).hexdigest()
  ```
* **What was wrong with it**:
  When tested against SQLite and PostgreSQL, `test_cryptographic_hash_chains_are_valid` failed!
  Database drivers deserialize `DateTime` fields with slight format discrepancies compared to Python's in-memory `datetime.now(timezone.utc).isoformat()` (e.g. SQLite drops the `+00:00` suffix and trailing microseconds). Because SHA-256 is strictly deterministic, even a single character mismatch causes valid ledger chains to be flagged as corrupt!
* **What I did instead**:
  Standardized datetime formatting to an exact string specification across both write and read paths:
  ```python
  timestamp_str = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
  payload = f"{prev_hash}|{account_id}|{transaction_id}|{entry_type}|{amount:.4f}|{running_balance:.4f}|{timestamp_str}"
  return hashlib.sha256(payload.encode("utf-8")).hexdigest()
  ```
  Verified that tamper detection accurately distinguishes between intact chains and deliberate database modifications.
* **Associated Commit**: `fix(ledger): normalize timestamp format in SHA-256 hash chain verification`

