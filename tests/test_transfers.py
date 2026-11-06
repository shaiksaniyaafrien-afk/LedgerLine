from decimal import Decimal
from tests.conftest import get_token_for


def test_deposit_and_withdrawal_flow(client, test_users):
    token = get_token_for(test_users["alice"])
    acc_id = test_users["alice_acc"].id

    # Read starting balance
    start_res = client.get(f"/api/accounts/{acc_id}", headers={"Authorization": f"Bearer {token}"})
    start_balance = float(start_res.json()["balance"])

    # Deposit 500
    dep_res = client.post(
        "/api/transactions/deposit",
        headers={"Authorization": f"Bearer {token}"},
        json={"account_id": acc_id, "amount": 500.0, "description": "Deposit test"},
    )
    assert dep_res.status_code == 200
    assert dep_res.json()["status"] == "COMPLETED"

    # Withdraw 200
    wth_res = client.post(
        "/api/transactions/withdraw",
        headers={"Authorization": f"Bearer {token}"},
        json={"account_id": acc_id, "amount": 200.0, "description": "Withdraw test"},
    )
    assert wth_res.status_code == 200
    assert wth_res.json()["status"] == "COMPLETED"

    # Check updated balance: exactly start_balance + 500 - 200
    acc_res = client.get(
        f"/api/accounts/{acc_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert acc_res.status_code == 200
    assert float(acc_res.json()["balance"]) == start_balance + 300.0


def test_transfer_between_accounts(client, test_users):
    token = get_token_for(test_users["alice"])
    alice_acc_id = test_users["alice_acc"].id
    bob_acc_num = test_users["bob_acc"].account_number

    # Read initial balances
    alice_start = float(client.get(f"/api/accounts/{alice_acc_id}", headers={"Authorization": f"Bearer {token}"}).json()["balance"])
    bob_token = get_token_for(test_users["bob"])
    bob_start = float(client.get(f"/api/accounts/{test_users['bob_acc'].id}", headers={"Authorization": f"Bearer {bob_token}"}).json()["balance"])

    # Transfer 300 from Alice to Bob
    res = client.post(
        "/api/transactions/transfer",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "source_account_id": alice_acc_id,
            "destination_account_number": bob_acc_num,
            "amount": 300.0,
            "description": "Payment to Bob",
        },
    )
    assert res.status_code == 200
    assert res.json()["status"] == "COMPLETED"

    # Alice balance reduced by exactly 300
    alice_res = client.get(f"/api/accounts/{alice_acc_id}", headers={"Authorization": f"Bearer {token}"})
    assert float(alice_res.json()["balance"]) == alice_start - 300.0

    # Bob balance increased by exactly 300
    bob_res = client.get(f"/api/accounts/{test_users['bob_acc'].id}", headers={"Authorization": f"Bearer {bob_token}"})
    assert float(bob_res.json()["balance"]) == bob_start + 300.0


def test_transfer_insufficient_funds_records_refusal(client, test_users):
    token = get_token_for(test_users["alice"])
    alice_acc_id = test_users["alice_acc"].id
    bob_acc_num = test_users["bob_acc"].account_number

    # Attempt to transfer 999999 (far exceeds available balance)
    res = client.post(
        "/api/transactions/transfer",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "source_account_id": alice_acc_id,
            "destination_account_number": bob_acc_num,
            "amount": 999999.0,
            "description": "Overdraft attempt",
        },
    )
    assert res.status_code == 400
    assert "Insufficient funds" in res.json()["detail"]

    # Verify refused attempt appears in statement!
    stmt_res = client.get(
        f"/api/accounts/{alice_acc_id}/statement",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert stmt_res.status_code == 200
    entries = stmt_res.json()["statement_entries"]
    refused_entries = [e for e in entries if e["entry_type"] == "REFUSED"]
    assert len(refused_entries) >= 1
    assert refused_entries[-1]["refusal_reason"] == "INSUFFICIENT_FUNDS"
    assert float(refused_entries[-1]["amount"]) == 999999.0


def test_transfer_to_same_account_rejected(client, test_users):
    token = get_token_for(test_users["alice"])
    alice_acc_id = test_users["alice_acc"].id
    alice_acc_num = test_users["alice_acc"].account_number

    res = client.post(
        "/api/transactions/transfer",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "source_account_id": alice_acc_id,
            "destination_account_number": alice_acc_num,
            "amount": 50.0,
        },
    )
    assert res.status_code == 400
    assert "Cannot transfer money to the same account" in res.json()["detail"]
