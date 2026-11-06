from tests.conftest import get_token_for


def test_create_account_by_customer(client, test_users):
    token = get_token_for(test_users["alice"])
    res = client.post(
        "/api/accounts",
        headers={"Authorization": f"Bearer {token}"},
        json={"currency": "INR", "initial_deposit": 250.0},
    )
    assert res.status_code == 201
    data = res.json()
    assert data["user_id"] == test_users["alice"].id
    assert float(data["balance"]) == 250.0
    assert data["account_number"].startswith("ACC-")


def test_auditor_cannot_create_account(client, test_users):
    token = get_token_for(test_users["auditor"])
    res = client.post(
        "/api/accounts",
        headers={"Authorization": f"Bearer {token}"},
        json={"currency": "INR", "initial_deposit": 100.0},
    )
    assert res.status_code == 403
    assert "read-only" in res.json()["detail"].lower()


def test_account_isolation_in_listing(client, test_users):
    alice_token = get_token_for(test_users["alice"])
    bob_token = get_token_for(test_users["bob"])
    admin_token = get_token_for(test_users["admin"])

    # Alice views her accounts
    res_alice = client.get("/api/accounts", headers={"Authorization": f"Bearer {alice_token}"})
    assert res_alice.status_code == 200
    alice_accs = res_alice.json()
    for acc in alice_accs:
        assert acc["user_id"] == test_users["alice"].id

    # Admin views all accounts
    res_admin = client.get("/api/accounts", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_admin.status_code == 200
    admin_accs = res_admin.json()
    assert len(admin_accs) >= len(alice_accs)

