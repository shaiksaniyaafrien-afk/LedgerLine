from decimal import Decimal
from tests.conftest import get_token_for, TestingSessionLocal
from app.models.ledger import LedgerEntry
from app.services.ledger_service import LedgerService


def test_system_reconciliation_invariant_holds(client, test_users):
    auditor_token = get_token_for(test_users["auditor"])

    res = client.get(
        "/api/audit/reconciliation",
        headers={"Authorization": f"Bearer {auditor_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_balanced"] is True
    assert float(data["discrepancy"]) == 0.0
    assert float(data["total_customer_balances"]) >= 0.0


def test_cryptographic_hash_chains_are_valid(client, test_users):
    auditor_token = get_token_for(test_users["auditor"])

    res = client.get(
        "/api/audit/tamper-check",
        headers={"Authorization": f"Bearer {auditor_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["all_chains_valid"] is True
    for item in data["details"]:
        assert item["is_valid"] is True


def test_tamper_detection_flags_corrupted_row(client, test_users):
    """
    Simulates malicious database alteration attack:
    An attacker attempts to alter a ledger amount directly in the database table.
    The cryptographic auditor verification must immediately detect the mismatch,
    flag all_chains_valid as False, and report the corrupted entry ID!
    """
    db = TestingSessionLocal()
    auditor_token = get_token_for(test_users["auditor"])

    # Find any existing ledger entry
    entry = db.query(LedgerEntry).first()
    if entry:
        original_amount = entry.amount
        entry_id = entry.id

        # Tamper with the row amount directly behind the scenes
        entry.amount = Decimal("99999.0000")
        db.commit()

        # Auditor runs verification
        res = client.get(
            "/api/audit/tamper-check",
            headers={"Authorization": f"Bearer {auditor_token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["all_chains_valid"] is False

        # Find the corrupted account report
        corrupted_reports = [d for d in data["details"] if not d["is_valid"]]
        assert len(corrupted_reports) > 0
        assert any(d["corrupted_entry_id"] == entry_id for d in corrupted_reports)

        # Restore original data
        entry.amount = original_amount
        db.commit()
    db.close()
