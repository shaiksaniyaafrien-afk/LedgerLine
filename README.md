# LedgerLine — Money Movement with a Ledger You Can Prove

> **Move money so the books always balance and the same request never pays twice.**  
> A high-integrity digital banking and double-entry ledger platform with cryptographic tamper-evidence, atomic concurrency safety, and idempotent execution.

---

## 1. Quick Credentials for Evaluation & Testing

The application automatically seeds standard accounts for all required personas upon first startup:

| Role | Username | Password | Default Account | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Administrator** | `admin` | `AdminPassword123!` | System Reserve | Full system view, user/account administration, system invariant inspection. |
| **Account Holder (Alice)** | `alice` | `AlicePassword123!` | `ACC-ALICE-101` | Balance: ₹5,000.00. Can deposit, withdraw, transfer, and view own statement. |
| **Account Holder (Bob)** | `bob` | `BobPassword123!` | `ACC-BOB-202` | Balance: ₹2,500.00. Target recipient for transfers and cross-account attacks. |
| **Auditor (Read-Only)** | `auditor` | `AuditorPassword123!` | Read-Only | Mathematical invariant verification, cryptographic hash chain validator, audit trail. **Blocked from moving money.** |

---

## 2. Core Guarantees & Architectural Model

### 1. Conservation of Money
Money is never created or destroyed.
- **Double-Entry Bookkeeping**: Every movement generates equal and opposite debit and credit postings.
- **Internal Transfers**: Net to zero ($\Delta \text{Circulation} = 0$).
- **External Deposits & Withdrawals**: Offset by the system clearing reserve account (`SYS-CLEARING-RESERVE`).
- **Global Invariant**:
  $$\sum \text{Customer Balances} = \sum \text{External Deposits} - \sum \text{External Withdrawals}$$
  Verified in real-time via `GET /api/audit/reconciliation` (Discrepancy must equal `0.0000`).

### 2. Strict Zero Floor (No Unauthorized Overdrafts)
No account balance can be driven negative, even under heavy concurrent requests:
1. **Deterministic Lock Ordering**: Row locks acquired in ascending ID order to eliminate database deadlocks.
2. **Atomic Compare-and-Swap Update**:
   ```sql
   UPDATE accounts 
   SET balance = balance - :amount 
   WHERE id = :account_id AND balance >= :amount;
   ```
   If `rowcount == 0`, the transaction is refused atomically.
3. **Database Check Constraint**: `CONSTRAINT chk_account_balance_non_negative CHECK (balance >= 0)`.

### 3. Exactly-Once Idempotency
- Every money-moving request supports an `Idempotency-Key` header (or JSON field).
- Requests are hashed canonically: `SHA-256(endpoint + canonical_sorted_json)`.
- Replaying the identical request returns the cached result with header `Idempotent-Replay: true` and payload field `is_duplicate: true` without moving money a second time.
- Submitting the same key with conflicting parameters returns `422 Unprocessable Content`.
- In-flight requests with the same key receive `409 Conflict`.

### 4. Cryptographic Tamper-Proof Audit Chain
Every ledger entry includes `prev_hash` and `entry_hash = SHA256(prev_hash | account_id | txn_id | type | amount | balance | timestamp)`.
- If an attacker modifies an amount, deletes a row, or reorders history in the database, the hash chain breaks immediately.
- The Auditor Console includes a **Run Full Audit Verification** tool that re-computes every hash from disk and pinpoints the exact corrupted entry.

### 5. Append-Only Refused Attempt Tracking
Statements and audit logs record every debit, every credit, and **every refused attempt** (insufficient funds, unauthorized cross-account transfer, inactive account) with the attempted amount, unmodified running balance, and actor ID.

---

## 3. Technology Stack

- **Backend**: Python 3.13, FastAPI (REST API), Uvicorn (ASGI server).
- **ORM & Data Layer**: SQLAlchemy 2.0 with type-safe `Numeric(18, 4)` precision.
- **Database Engine**: PostgreSQL (Neon Cloud) for production deployment; SQLite with WAL mode & foreign keys for offline/testing.
- **Security**: Native `bcrypt` (12 rounds) password hashing, HMAC-SHA256 JWT bearer tokens.
- **Testing**: `pytest` with multithreaded concurrency, deadlock, idempotency, and tamper detection tests.
- **Frontend**: Clean modern responsive web UI (HTML5, Tailwind CSS, FontAwesome, Vanilla JS) with quick 1-click persona switcher.

---

## 4. API Documentation

| Method | Endpoint | Allowed Roles | Effect on Money | Description |
| :--- | :--- | :--- | :--- | :--- |
| `POST` | `/api/auth/register` | Public | None | Register a new user and generate a default account. |
| `POST` | `/api/auth/login` | Public | None | Authenticate with username & password; returns JWT token. |
| `GET` | `/api/auth/me` | Authenticated | None | Returns profile and active role of current user. |
| `POST` | `/api/accounts` | Admin, Holder | None | Open a new bank account. (Auditors forbidden). |
| `GET` | `/api/accounts` | Authenticated | None | List accounts. Holders see own accounts; Admins/Auditors see all. |
| `GET` | `/api/accounts/{id}` | Admin, Auditor, Owner | None | View account balance and metadata. |
| `GET` | `/api/accounts/{id}/statement` | Admin, Auditor, Owner | None | View full statement: debits, credits, refused attempts, and hash proofs. |
| `POST` | `/api/transactions/deposit` | Admin, Owner | **Increases Customer Balance** | Credits account, debits clearing reserve. Idempotent. |
| `POST` | `/api/transactions/withdraw` | Admin, Owner | **Decreases Customer Balance** | Debits account, credits clearing reserve. Enforces zero floor. Idempotent. |
| `POST` | `/api/transactions/transfer` | Admin, Owner | **Nets to Zero** | Debits source account, credits destination account. Atomic & deadlock-safe. |
| `GET` | `/api/audit/reconciliation` | Admin, Auditor | None | Computes global system invariant and proves balance discrepancy == 0.0000. |
| `GET` | `/api/audit/tamper-check` | Admin, Auditor | None | Validates cryptographic SHA-256 hash chains across all account ledgers. |
| `GET` | `/api/audit/logs` | Admin, Auditor | None | Immutable event trail of logins, movements, and refused attacks. |

---

## 5. Local Setup & Running Tests

### 1. Setup Virtual Environment
```bash
# Clone the repository
git clone https://github.com/your-username/LedgerLine.git
cd LedgerLine

# Create and activate virtual environment
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
*(By default, the application runs with Neon PostgreSQL if configured, or falls back seamlessly to local SQLite if offline or running tests).*

### 3. Run Automated Pytest Suite
Execute the full test suite covering concurrency races, idempotency retries, authorization rules, and ledger tamper verification:
```bash
pytest
```
*Expected result: 22 passed in ~4.5 seconds.*

### 4. Run Web Application
```bash
uvicorn app.main:app --reload --port 8000
```
Open your browser at: [http://localhost:8000/login](http://localhost:8000/login).
Use the **Quick Role Switcher** buttons to immediately test as Alice, Bob, Admin, or Auditor.

---

## 6. What Was Built vs. What Was Deliberately Omitted

### Built
- Full double-entry ledger with immutable debits, credits, and refused attempts.
- Cryptographic SHA-256 hash chaining on all ledger blocks.
- Real-time mathematical invariant reconciliation endpoint.
- Atomic compare-and-swap balance updates preventing concurrent overdrafts.
- Ascending ID lock acquisition preventing deadlocks during cross-transfers.
- Idempotency engine with canonical request payload hashing and in-flight collision protection.
- Role-based access control (`admin`, `account_holder`, `auditor`) enforced on every request.
- Modern responsive banking frontend with statement explorer and auditor verification portal.

### Deliberately Omitted
- **Multi-Currency Dynamic FX Conversion**: Left out to preserve exact mathematical invariant conservation without external exchange-rate volatility risks.
- **Physical ATM / Card Integration**: Beyond the core integrity focus of LedgerLine.
- **Autonomous AI-Driven Money Movement**: Explicitly excluded per project guidelines—AI should only flag anomalies, while humans authorize all money movements.
