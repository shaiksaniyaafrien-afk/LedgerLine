from tests.conftest import get_token_for


def test_user_cannot_withdraw_from_another_users_account(client, test_users):
    alice_token = get_token_for(test_users["alice"])
    bob_acc_id = test_users["bob_acc"].id

    # Alice tries to withdraw from Bob's account
    res = client.post(
        "/api/transactions/withdraw",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={"account_id": bob_acc_id, "amount": 100.0},
    )
    assert res.status_code == 403
    assert "cannot withdraw" in res.json()["detail"].lower()


def test_user_cannot_transfer_out_of_another_users_account(client, test_users):
    bob_token = get_token_for(test_users["bob"])
    alice_acc_id = test_users["alice_acc"].id

    # Bob tries to initiate a transfer taking Alice's money to Bob
    res = client.post(
        "/api/transactions/transfer",
        headers={"Authorization": f"Bearer {bob_token}"},
        json={
            "source_account_id": alice_acc_id,
            "destination_account_number": test_users["bob_acc"].account_number,
            "amount": 500.0,
        },
    )
    assert res.status_code == 403
    assert "cannot transfer funds out of an account you do not own" in res.json()["detail"]


def test_auditor_cannot_move_money(client, test_users):
    auditor_token = get_token_for(test_users["auditor"])
    alice_acc_id = test_users["alice_acc"].id

    # Auditor deposit attempt
    dep_res = client.post(
        "/api/transactions/deposit",
        headers={"Authorization": f"Bearer {auditor_token}"},
        json={"account_id": alice_acc_id, "amount": 100.0},
    )
    assert dep_res.status_code == 403

    # Auditor withdraw attempt
    wth_res = client.post(
        "/api/transactions/withdraw",
        headers={"Authorization": f"Bearer {auditor_token}"},
        json={"account_id": alice_acc_id, "amount": 100.0},
    )
    assert wth_res.status_code == 403

    # Auditor transfer attempt
    trf_res = client.post(
        "/api/transactions/transfer",
        headers={"Authorization": f"Bearer {auditor_token}"},
        json={
            "source_account_id": alice_acc_id,
            "destination_account_number": test_users["bob_acc"].account_number,
            "amount": 100.0,
        },
    )
    assert trf_res.status_code == 403


def test_unauthenticated_requests_blocked(client, test_users):
    res = client.post(
        "/api/transactions/transfer",
        json={
            "source_account_id": test_users["alice_acc"].id,
            "destination_account_number": test_users["bob_acc"].account_number,
            "amount": 50.0,
        },
    )
    assert res.status_code == 401

