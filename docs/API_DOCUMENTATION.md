# LedgerLine — API Specification & Security Reference

> **Comprehensive API Reference for LedgerLine**  
> Specifying endpoint contracts, access control rules, effects on money, and error responses.

---

## 1. Authentication & Headers

### Authentication
All protected routes require an HTTP `Authorization` header containing a valid JSON Web Token (JWT):
```http
Authorization: Bearer <access_token>
```

### Idempotency Headers
Money-moving routes (`/api/transactions/*`) accept an optional but strongly recommended client idempotency key:
```http
Idempotency-Key: <unique-uuid-or-client-string>
```
* **First invocation**: Executes the transfer and caches the response.
* **Replayed invocation**: Returns the identical response payload with HTTP header `Idempotent-Replay: true` and JSON field `"is_duplicate": true` without debiting accounts a second time.
* **In-flight concurrent call**: Returns `409 Conflict`.
* **Mismatched payload reuse**: Returns `422 Unprocessable Content`.

---

## 2. Role-Based Access Control Matrix

| Route | Method | Administrator | Account Holder | Auditor | Effect on Money |
| :--- | :---: | :---: | :---: | :---: | :--- |
| `/api/auth/register` | `POST` | Public | Public | Public | None |
| `/api/auth/login` | `POST` | Public | Public | Public | None |
| `/api/auth/me` | `GET` | Allowed | Allowed | Allowed | None |
| `/api/accounts` | `POST` | Any User | Own Account | **Forbidden (403)** | None |
| `/api/accounts` | `GET` | All Accounts | Own Accounts | All Accounts | None |
| `/api/accounts/{id}` | `GET` | All Accounts | Own Account | All Accounts | None |
| `/api/accounts/{id}/statement` | `GET` | All Accounts | Own Account | All Accounts | None |
| `/api/transactions/deposit` | `POST` | Allowed | Own Account | **Forbidden (403)** | Credits account, debits system reserve |
| `/api/transactions/withdraw` | `POST` | Allowed | Own Account | **Forbidden (403)** | Debits account, credits system reserve |
| `/api/transactions/transfer` | `POST` | Allowed | Own Account | **Forbidden (403)** | Debits source, credits destination (Nets to zero) |
| `/api/audit/reconciliation` | `GET` | Allowed | **Forbidden (403)** | Allowed | None (Read-only verification) |
| `/api/audit/tamper-check` | `GET` | Allowed | **Forbidden (403)** | Allowed | None (Read-only hash audit) |
| `/api/audit/logs` | `GET` | Allowed | **Forbidden (403)** | Allowed | None (Read-only audit trail) |

---

## 3. Endpoints Detail

### 3.1 Authentication

#### `POST /api/auth/register`
Creates a user account and auto-provisions an initial customer account with ₹1,000.00 starter balance.
* **Request Body**:
  ```json
  {
    "username": "charlie",
    "email": "charlie@example.com",
    "password": "Password123!",
    "full_name": "Charlie Davis",
    "role": "account_holder"
  }
  ```
* **Response `200 OK`**:
  ```json
  {
    "id": 5,
    "username": "charlie",
    "email": "charlie@example.com",
    "full_name": "Charlie Davis",
    "role": "account_holder",
    "is_active": true,
    "created_at": "2026-11-06T12:00:00Z"
  }
  ```

#### `POST /api/auth/login`
Authenticates credentials and returns a Bearer JWT token.
* **Request Body**:
  ```json
  {
    "username": "alice",
    "password": "AlicePassword123!"
  }
  ```
* **Response `200 OK`**:
  ```json
  {
    "access_token": "eyJhbGciOiJIUzI1NiIsIn...",
    "token_type": "bearer",
    "user_id": 3,
    "username": "alice",
    "role": "account_holder",
    "full_name": "Alice Smith"
  }
  ```

---

### 3.2 Account Operations

#### `POST /api/accounts`
Opens a new bank account.
* **Headers**: `Authorization: Bearer <token>`
* **Request Body**:
  ```json
  {
    "currency": "INR",
    "initial_deposit": 500.00
  }
  ```
* **Response `201 Created`**:
  ```json
  {
    "id": 6,
    "account_number": "ACC-49182391",
    "user_id": 3,
    "account_type": "CUSTOMER",
    "balance": "500.0000",
    "currency": "INR",
    "status": "ACTIVE",
    "created_at": "2026-11-06T12:05:00Z"
  }
  ```

#### `GET /api/accounts/{account_id}/statement`
Returns full ledger history for an account, including credits, debits, running balances, cryptographic hashes, and refused attempts.
* **Response `200 OK`**:
  ```json
  {
    "account_id": 3,
    "account_number": "ACC-ALICE-101",
    "current_balance": "5000.0000",
    "currency": "INR",
    "owner_name": "Alice Smith",
    "statement_entries": [
      {
        "entry_id": 1,
        "transaction_id": 1,
        "transaction_reference": "DEP-3F9A1B2C",
        "transaction_type": "DEPOSIT",
        "entry_type": "CREDIT",
        "amount": "5000.0000",
        "running_balance": "5000.0000",
        "refusal_reason": null,
        "initiated_by_name": "System Administrator",
        "initiated_by_user_id": 1,
        "entry_hash": "a8f5c3b1e9d2...",
        "prev_hash": "GENESIS",
        "created_at": "2026-11-06T12:00:00Z"
      },
      {
        "entry_id": 4,
        "transaction_id": 3,
        "transaction_reference": "TRF-REF-99A1",
        "transaction_type": "TRANSFER",
        "entry_type": "REFUSED",
        "amount": "99999.0000",
        "running_balance": "5000.0000",
        "refusal_reason": "INSUFFICIENT_FUNDS",
        "initiated_by_name": "Alice Smith",
        "initiated_by_user_id": 3,
        "entry_hash": "f4c910ab38d...",
        "prev_hash": "a8f5c3b1e9d2...",
        "created_at": "2026-11-06T12:10:00Z"
      }
    ]
  }
  ```

---

### 3.3 Money Movements

#### `POST /api/transactions/transfer`
Atomically moves funds between two accounts.
* **Headers**: `Authorization: Bearer <token>`, `Idempotency-Key: <uuid>`
* **Request Body**:
  ```json
  {
    "source_account_id": 3,
    "destination_account_number": "ACC-BOB-202",
    "amount": 250.00,
    "description": "Invoice payment"
  }
  ```
* **Response `200 OK`**:
  ```json
  {
    "id": 5,
    "reference": "TRF-E8D19F3A",
    "idempotency_key": "key-99a1b2c3",
    "transaction_type": "TRANSFER",
    "source_account_id": 3,
    "destination_account_id": 4,
    "amount": "250.0000",
    "currency": "INR",
    "status": "COMPLETED",
    "refusal_reason": null,
    "initiated_by_user_id": 3,
    "description": "Invoice payment",
    "created_at": "2026-11-06T12:15:00Z",
    "is_duplicate": false
  }
  ```
* **Error Response `400 Bad Request` (Insufficient Funds)**:
  ```json
  {
    "detail": "Transfer refused: Insufficient funds. Available balance: 50.0000"
  }
  ```
* **Error Response `403 Forbidden` (Unauthorized Account Access)**:
  ```json
  {
    "detail": "Access forbidden: You cannot transfer funds out of an account you do not own."
  }
  ```

---

### 3.4 Audit & Invariant Verification

#### `GET /api/audit/reconciliation`
Mathematically computes and verifies the global conservation of money across the system.
* **Headers**: `Authorization: Bearer <auditor_or_admin_token>`
* **Response `200 OK`**:
  ```json
  {
    "is_balanced": true,
    "total_customer_balances": "7500.0000",
    "total_external_deposits": "7500.0000",
    "total_external_withdrawals": "0.0000",
    "expected_customer_balances": "7500.0000",
    "discrepancy": "0.0000",
    "total_internal_transfers_volume": "1250.0000",
    "total_credits": "8750.0000",
    "total_debits": "8750.0000",
    "ledger_double_entry_balanced": true,
    "total_accounts": 3,
    "total_ledger_entries": 6,
    "total_refused_attempts": 1,
    "checked_at": "2026-11-06T12:30:00Z"
  }
  ```

#### `GET /api/audit/tamper-check`
Re-hashes every block in the ledger to prove no records were silently altered or deleted.
* **Response `200 OK`**:
  ```json
  {
    "all_chains_valid": true,
    "accounts_checked": 3,
    "total_entries_checked": 6,
    "details": [
      {
        "account_id": 3,
        "account_number": "ACC-ALICE-101",
        "is_valid": true,
        "total_entries_verified": 3,
        "corrupted_entry_id": null,
        "error_message": null
      }
    ],
    "checked_at": "2026-11-06T12:30:00Z"
  }
  ```
