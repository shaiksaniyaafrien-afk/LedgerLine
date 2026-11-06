# LedgerLine — Threat Model & Security Architecture (`THREATS.md`)

This document defines the threat landscape for **LedgerLine**, detailing the adversarial attack vectors identified, the defensive mechanisms implemented at the architectural and database levels, how each is verified via automated tests, and the risks consciously accepted.

---

## 1. Threat Matrix & Defense Breakdown

| Threat ID | Adversarial Attack Vector | Severity | Architectural Defense | Verification Test |
| :--- | :--- | :--- | :--- | :--- |
| **THREAT-01** | **Concurrent Overdraft Race**<br>Simultaneous withdrawal requests fired at the exact same millisecond to spend past balance. | **Critical** | Three layers of defense:<br>1. Deterministic row locking (`SELECT ... FOR UPDATE`).<br>2. Atomic compare-and-swap SQL update: `UPDATE accounts SET balance = balance - :amount WHERE id = :id AND balance >= :amount`.<br>3. Database check constraint: `CONSTRAINT chk_account_balance_non_negative CHECK (balance >= 0)`. | `test_concurrency.py::test_concurrent_withdrawals_cannot_overdraw`<br>(10 threads fire simultaneous $100 withdrawals against a $200 account; exactly 2 succeed, 8 fail with 400 Insufficient Funds, balance stays 0.00). |
| **THREAT-02** | **Cross-Transfer Database Deadlock**<br>Thread 1 transfers A &rarr; B while Thread 2 transfers B &rarr; A at the exact same instant. | **High** | **Ascending Row-Lock Ordering**:<br>Locks are strictly acquired in ascending order of account IDs (`min(A, B)` followed by `max(A, B)`). This guarantees that neither transaction can hold a resource the other needs in reverse order. | `test_concurrency.py::test_concurrent_bidirectional_transfers_conserve_total`<br>(20 threads transferring bidirectionally with zero deadlocks). |
| **THREAT-03** | **Network Replay / Duplicate Payment**<br>Client experiences timeout or double-clicks payment; request is submitted twice with same Idempotency-Key. | **Critical** | **Atomic Idempotency Engine**:<br>Stores `(user_id, key, request_hash, status, response_body)`. First request acquires processing lock; replayed requests receive the cached result with `Idempotent-Replay: true` header and `is_duplicate: true`. Money moves strictly once. | `test_idempotency.py::test_idempotent_transfer_replay_does_not_pay_twice` |
| **THREAT-04** | **Idempotency Key Payload Substitution**<br>Adversary reuses a previously generated idempotency key with different payment details (e.g. changing recipient or amount). | **High** | **Canonical Request Hashing**:<br>Each idempotency record stores `SHA-256(endpoint + canonical_sorted_json_payload)`. A key reused with conflicting parameters is rejected with `422 Unprocessable Content`. | `test_idempotency.py::test_idempotency_key_payload_conflict_rejected` |
| **THREAT-05** | **Cross-Tenant Money Movement (IDOR)**<br>User Alice attempts to withdraw or transfer funds out of User Bob's account by specifying Bob's account ID. | **Critical** | **Server-Enforced Ownership Gate**:<br>Every money-moving endpoint verifies `account.user_id == current_user.id` on the server before acquiring locks or executing logic. Violations immediately log a `REFUSED` attempt with reason `UNAUTHORIZED_ACCOUNT_ACCESS` and return `403 Forbidden`. | `test_authorization.py::test_user_cannot_withdraw_from_another_users_account`<br>`test_authorization.py::test_user_cannot_transfer_out_of_another_users_account` |
| **THREAT-06** | **Auditor Privilege Escalation**<br>Auditor token used to call money-moving endpoints (deposit, withdrawal, transfer) or create accounts. | **High** | **Strict Read-Only Enforcement**:<br>Auditors are blocked at the controller layer with `HTTP 403 Forbidden` on all POST/PUT/DELETE routes. They have read-only visibility into ledger reconciliation and tamper reports. | `test_authorization.py::test_auditor_cannot_move_money`<br>`test_accounts.py::test_auditor_cannot_create_account` |
| **THREAT-07** | **Silent Ledger Row Manipulation**<br>Corrupt database administrator or SQL injection attacker alters an amount or deletes an audit/ledger row to cover a theft. | **Critical** | **Cryptographic SHA-256 Hash Chaining**:<br>Each ledger entry contains `prev_hash` and `entry_hash = SHA256(prev_hash + account_id + transaction_id + entry_type + amount + running_balance + timestamp)`. Any modified, inserted, or deleted row breaks the chain immediately. | `test_ledger.py::test_tamper_detection_flags_corrupted_row`<br>(Deliberately alters an entry amount directly in DB; auditor verification immediately flags `all_chains_valid = False` and outputs the corrupted entry ID). |
| **THREAT-08** | **System Conservation Invariant Violation**<br>Money created or destroyed out of thin air due to unbalanced postings or unrecorded adjustments. | **Critical** | **Double-Entry Bookkeeping Model**:<br>Every transaction creates dual debit and credit postings. External deposits debit the `SYSTEM_CLEARING_RESERVE` account and credit the customer account. Total money in circulation strictly satisfies: $\sum \text{Customer Balances} = \sum \text{External Deposits} - \sum \text{External Withdrawals}$. | `test_ledger.py::test_system_reconciliation_invariant_holds`<br>(Auditor reconciliation endpoint verifies system discrepancy is exactly 0.0000). |
| **THREAT-09** | **Floating Point Currency Rounding Errors**<br>IEEE 754 float rounding inaccuracies (e.g., $0.1 + 0.2 = 0.30000000000000004$) accumulating over millions of transfers. | **High** | **Arbitrary-Precision Decimal Representation**:<br>All balances, transaction amounts, and ledger records use `Numeric(18, 4)` in the database and Python's `Decimal` module with strict 4-decimal place scaling. Zero floating point types are used. | Covered across all transaction and ledger unit tests. |
| **THREAT-10** | **Statement Deletion / Hidden Refusal**<br>Adversary attempts to hide a failed overdraw or unauthorized transfer attempt. | **Medium** | **Append-Only Refused Attempt Logging**:<br>Refused transactions generate permanent `Transaction` and `LedgerEntry` records with `entry_type = REFUSED` and a non-nullable refusal reason. Balance remains untouched while the attempt is cryptographically chained into the account statement. | `test_transfers.py::test_transfer_insufficient_funds_records_refusal` |

---

## 2. Deep Dive: Concurrency & Atomicity Strategy

### Concurrency Race Prevention
When concurrent requests arrive to move funds from account $A$:
1. A transaction is initiated with strict serializability or row locking (`SELECT ... FOR UPDATE`).
2. Deadlocks are avoided by sorting account IDs in ascending order prior to acquisition:
   $$\text{lock\_order} = [\min(\text{from\_id}, \text{to\_id}), \max(\text{from\_id}, \text{to\_id})]$$
3. An atomic SQL conditional decrement is executed:
   ```sql
   UPDATE accounts 
   SET balance = balance - :amount 
   WHERE id = :account_id AND balance >= :amount;
   ```
4. If `rowcount == 0`, the balance was insufficient or already consumed by a racing request. A `REFUSED` ledger entry is appended to the audit trail, the transaction commits the refusal record, and an HTTP 400 error is returned to the client.
5. If `rowcount == 1`, the corresponding credit is posted to the destination account, double-entry ledger rows are generated, hash chains are updated, and the transaction is committed.

---

## 3. Cryptographic Tamper-Proof Audit Chain

The ledger does not rely solely on database access controls. Every row is cryptographically chained:

```
[GENESIS Block]
       ↓
[LedgerEntry #1] ─── Hash: SHA256("GENESIS" | acc_id | txn_id | CREDIT | 1000.0000 | 1000.0000 | timestamp)
       ↓
[LedgerEntry #2] ─── Hash: SHA256(Hash#1 | acc_id | txn_id | DEBIT  |  200.0000 |  800.0000 | timestamp)
       ↓
[LedgerEntry #3] ─── Hash: SHA256(Hash#2 | acc_id | txn_id | REFUSED|  900.0000 |  800.0000 | timestamp)
```

The auditor endpoint `/api/audit/tamper-check` iterates across all accounts and re-computes every hash from disk. If even a single bit in `amount`, `entry_type`, `running_balance`, or sequence order has been modified, the computation diverges from `stored_hash`, identifying the exact entry ID that was tampered with.

---

## 4. Knowingly Accepted Risks & Mitigations

1. **Physical Database Host Destruction**:
   - *Risk*: A total failure of the cloud database provider without backups could result in data loss.
   - *Mitigation*: Automated Point-In-Time-Recovery (PITR) and replication provided by Neon PostgreSQL / cloud managed infrastructure.

2. **Distributed Clock Drift Across Multiple Application Nodes**:
   - *Risk*: If multiple application instances run on disparate servers with unsynchronized system clocks, timestamps in audit entries could exhibit micro-second drift.
   - *Mitigation*: Ledger sequencing and hash chains are strictly keyed to database autoincrementing transaction sequence numbers and normalized UTC timestamps formatted to ISO second precision. Sequence ordering is deterministic regardless of host clock jitter.

3. **In-Flight Idempotency Key Lock Timeout**:
   - *Risk*: If a worker process dies mid-transaction while an idempotency key is marked as `PROCESSING`, subsequent requests with that key could receive a `409 Conflict`.
   - *Mitigation*: Idempotency records track `created_at` and `updated_at`. If an in-flight key is older than 60 seconds without completion, the idempotency service permits re-acquiring the key.
