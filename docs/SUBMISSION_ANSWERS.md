# LedgerLine — Official Submission Form Answers (`SUBMISSION_ANSWERS.md`)

Use these pre-drafted answers when filling out **Step 3 (My Submission)** on [hackathon.snovasys.com](https://hackathon.snovasys.com).

---

### Project Title
**LedgerLine**

### One-Line Description
*A high-integrity digital banking and double-entry ledger platform with cryptographic tamper-evidence, atomic concurrency safety, and idempotent execution.*

---

### Question 1: What did you build?
We built LedgerLine, an integrity-first financial ledger system designed around the core principle that money must never be created, destroyed, or double-spent. The architecture features:
1. **Double-Entry Bookkeeping Engine**: Every deposit, withdrawal, and transfer produces balanced debit and credit entries. External movements are counter-balanced against a system clearing reserve (`SYS-CLEARING-RESERVE`), while internal transfers net strictly to zero ($\sum \Delta = 0$).
2. **Three-Tier Role Security**: Enforces distinct server-side permission gates on every request for `admin` (system management), `account_holder` (isolated to own accounts), and `auditor` (strictly read-only observer, forbidden from moving money).
3. **Cryptographic Tamper-Proof Audit Chain**: An append-only ledger where every entry is chained using SHA-256 (`entry_hash = SHA256(prev_hash | account_id | txn_id | type | amount | balance | timestamp)`). Any modification or row deletion breaks the chain and is detected by the auditor tool.
4. **Append-Only Refused Attempt Tracking**: Statements and audit logs permanently record every credit, debit, and refused attempt (e.g., insufficient funds, unauthorized access) with the attempted amount and unmodified running balance.
5. **Modern Banking Web UI**: Built with responsive HTML5, Tailwind CSS, and Vanilla JS, featuring account overview cards, a transfer modal with visible idempotency keys, real-time statement inspection, an auditor reconciliation console, and a 1-click persona switcher.

---

### Question 2: Your integrity & concurrency model in your own words
Our integrity and concurrency model guarantees that the books always balance and balances can never be driven negative, even when racing requests hit the server simultaneously:
- **Ascending Row-Lock Ordering**: To eliminate database deadlocks during concurrent bidirectional cross-transfers (e.g., Alice $\to$ Bob and Bob $\to$ Alice racing at the exact same millisecond), row locks (`SELECT ... FOR UPDATE`) are strictly acquired in ascending numerical order of account IDs:
  $$\text{lock\_order} = [\min(\text{from\_id}, \text{to\_id}), \max(\text{from\_id}, \text{to\_id})]$$
- **Atomic Compare-and-Swap Update**: Rather than relying on naive read-then-write checks in application memory, deductions are executed via an atomic SQL conditional statement:
  ```sql
  UPDATE accounts 
  SET balance = balance - :amount 
  WHERE id = :account_id AND balance >= :amount;
  ```
  If `rowcount == 0`, the balance was insufficient or already spent by a racing thread. The system records a `REFUSED` ledger entry, commits the refusal to the audit trail, and returns HTTP 400.
- **Database CHECK Constraint**: Backed by `CONSTRAINT chk_account_balance_non_negative CHECK (balance >= 0)` as a hard database invariant.
- **Global Conservation Invariant**:
  $$\sum \text{Customer Balances} = \sum \text{External Deposits} - \sum \text{External Withdrawals}$$
  Verified via `/api/audit/reconciliation` which calculates total customer balances against external inflows/outflows, proving the system discrepancy is exactly `0.0000`.

---

### Question 3: How idempotency works
Our idempotency engine guarantees that replaying a request (due to network retries, double-clicks, or timeouts) executes the movement exactly once:
1. **Key Extraction & Scoping**: Each money-moving request accepts an `Idempotency-Key` header, scoped to the authenticated `user_id`.
2. **Canonical Payload Hashing**: We compute `request_hash = SHA256(endpoint + canonical_sorted_json)`. If a client reuses an existing idempotency key with conflicting parameters (e.g. altering amount or destination), the server rejects it with `422 Unprocessable Content`.
3. **In-Flight Lock Protection**: An `idempotency_records` table tracks status as `PROCESSING`, `COMPLETED`, or `FAILED`. If a duplicate request arrives while the first is still processing, the server returns `409 Conflict`.
4. **Transparent Replay**: Once completed, subsequent requests with the same key bypass business logic and immediately return the original cached response with HTTP header `Idempotent-Replay: true` and body payload `"is_duplicate": true`.

---

### Question 4: How the audit trail and proof work
In LedgerLine, you can mathematically prove what happened and who authorized it:
- **Cryptographic SHA-256 Hash Chaining**: Every `LedgerEntry` contains the SHA-256 hash of the previous ledger row for that account (`prev_hash`), forming a verifiable blockchain. The Auditor endpoint `/api/audit/tamper-check` re-computes every block from disk; modifying even one cent in any historical transaction breaks the chain and reports the corrupted entry ID.
- **Append-Only Refused Attempt Logging**: Refused transactions are never discarded or rolled back. When a transfer fails (e.g., insufficient funds or cross-account access violation), a permanent `Transaction` and `LedgerEntry` are appended with `entry_type = REFUSED`, recording the attempted amount, current balance, initiated_by user ID, and refusal reason.
- **Audit Logs**: All user events (logins, failed authentication, account creation, and transfers) are logged to an immutable `audit_logs` table recording actor ID, IP address, and JSON event metadata.

---

### Question 5: How you used AI and where it was wrong
We used AI to accelerate scaffolding, initial schema definitions, and frontend components, but applied rigorous code review to catch and correct several critical architectural defects (documented in `PROMPTS.md`):
1. **Passlib Bcrypt Incompatibility**: AI generated standard `passlib.context.CryptContext(schemes=["bcrypt"])` which crashed on Python 3.13 due to `module 'bcrypt' has no attribute '__about__'`. We discarded passlib and implemented native `bcrypt` calls with explicit 72-byte truncation.
2. **Naive Application-Level Concurrency Check**: AI initially generated naive `if account.balance < amount:` read-then-write logic, which allowed concurrent threads to overdraw accounts past zero. We replaced it with atomic SQL compare-and-swap updates (`UPDATE ... WHERE balance >= :amount`) and ascending ID row locking.
3. **Silent Session Rollback for Refused Attempts**: AI handled failed transfers by rolling back the transaction (`db.rollback()`), which erased all evidence of refused attempts. We refactored it to record an append-only `REFUSED` ledger entry so statements show all attempted overdraws and attacks.
4. **Idempotency Without Payload Validation**: AI implemented a simple key check that returned old responses even if a client reused a key with different transfer parameters. We added canonical payload hashing (`SHA-256`) and in-flight conflict guards (`409 Conflict`).
5. **Hash Chain Serialization Desync**: AI used `.isoformat()` for timestamp hashing, which caused hash validation to fail between SQLite and PostgreSQL due to microsecond/timezone serialization differences. We standardized to `strftime("%Y-%m-%dT%H:%M:%SZ")`.

---

### Question 6: What you chose not to build, accepted risks, and what is unfinished
- **What We Chose Not to Build**:
  - *Dynamic Multi-Currency FX*: Deliberately excluded to keep the conservation of money invariant mathematically exact without introducing floating-point exchange-rate volatility risks.
  - *Autonomous AI Money Movement*: AI is strictly excluded from making financial decisions. AI should only flag anomalies; human authorization is mandatory for all transactions.
- **Accepted Risks**:
  - *In-Flight Worker Process Crash*: If an application server crashes mid-transaction while an idempotency key is marked `PROCESSING`, subsequent requests within 60 seconds receive `409 Conflict` until the record times out.
  - *Host Clock Jitter*: Timestamps across distributed containers could experience microsecond drift; ledger sequence ordering is anchored to monotonic database IDs and UTC seconds to remain deterministic.
- **Unfinished Work / Future Enhancements**:
  - Webhook delivery notifications for third-party consumers upon completed or refused transfers.
  - Granular multi-signature authorization workflows for large corporate transactions exceeding pre-set thresholds.
