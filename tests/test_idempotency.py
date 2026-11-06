import uuid
from tests.conftest import get_token_for


def test_idempotent_transfer_replay_does_not_pay_twice(client, test_users):
    token = get_token_for(test_users["alice"])
    alice_acc_id = test_users["alice_acc"].id
    bob_acc_num = test_users["bob_acc"].account_number

    # Read Alice initial balance
    init_res = client.get(f"/api/accounts/{alice_acc_id}", headers={"Authorization": f"Bearer {token}"})
    initial_balance = float(init_res.json()["balance"])

    idem_key = f"idem-test-{uuid.uuid4()}"
    payload = {
        "source_account_id": alice_acc_id,
        "destination_account_number": bob_acc_num,
        "amount": 150.0,
        "description": "Vendor Invoice Payment",
        "idempotency_key": idem_key,
    }

    # First call
    res1 = client.post(
        "/api/transactions/transfer",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": idem_key},
        json=payload,
    )
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["status"] == "COMPLETED"
    assert data1.get("is_duplicate", False) is False

    # Second call with identical key (simulating network timeout retry / double-click)
    res2 = client.post(
        "/api/transactions/transfer",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": idem_key},
        json=payload,
    )
    assert res2.status_code == 200
    data2 = res2.json()
    assert res2.headers.get("Idempotent-Replay") == "true"
    assert data2["is_duplicate"] is True
    assert data2["id"] == data1["id"]
    assert data2["reference"] == data1["reference"]

    # Check Alice balance after 2 calls: must have moved ONLY ONCE (150.0)
    after_res = client.get(f"/api/accounts/{alice_acc_id}", headers={"Authorization": f"Bearer {token}"})
    after_balance = float(after_res.json()["balance"])
    assert after_balance == initial_balance - 150.0


def test_idempotency_key_payload_conflict_rejected(client, test_users):
    token = get_token_for(test_users["alice"])
    alice_acc_id = test_users["alice_acc"].id
    bob_acc_num = test_users["bob_acc"].account_number

    idem_key = f"idem-conflict-{uuid.uuid4()}"

    # First call with amount 100
    res1 = client.post(
        "/api/transactions/transfer",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": idem_key},
        json={
            "source_account_id": alice_acc_id,
            "destination_account_number": bob_acc_num,
            "amount": 100.0,
            "idempotency_key": idem_key,
        },
    )
    assert res1.status_code == 200

    # Second call reusing SAME key with DIFFERENT amount 200 -> must return 422!
    res2 = client.post(
        "/api/transactions/transfer",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": idem_key},
        json={
            "source_account_id": alice_acc_id,
            "destination_account_number": bob_acc_num,
            "amount": 200.0,
            "idempotency_key": idem_key,
        },
    )
    assert res2.status_code == 422
    assert "collision" in res2.json()["detail"].lower()
