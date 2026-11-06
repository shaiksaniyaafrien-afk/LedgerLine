from app.models.user import UserRole


def test_register_account_holder(client):
    res = client.post(
        "/api/auth/register",
        json={
            "username": "new_customer",
            "email": "customer@example.com",
            "password": "CustomerPassword123!",
            "full_name": "New Customer",
            "role": "account_holder",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["username"] == "new_customer"
    assert data["role"] == "account_holder"
    assert "id" in data


def test_register_duplicate_username_fails(client):
    client.post(
        "/api/auth/register",
        json={
            "username": "dup_user",
            "email": "dup1@example.com",
            "password": "Password123!",
            "full_name": "Dup User",
        },
    )
    res = client.post(
        "/api/auth/register",
        json={
            "username": "dup_user",
            "email": "dup2@example.com",
            "password": "Password123!",
            "full_name": "Dup User 2",
        },
    )
    assert res.status_code == 400
    assert "already taken" in res.json()["detail"]


def test_login_successful_and_me(client):
    client.post(
        "/api/auth/register",
        json={
            "username": "login_user",
            "email": "login@example.com",
            "password": "CorrectPassword123!",
            "full_name": "Login User",
        },
    )
    res = client.post(
        "/api/auth/login",
        json={"username": "login_user", "password": "CorrectPassword123!"},
    )
    assert res.status_code == 200
    token = res.json()["access_token"]
    assert token is not None

    me_res = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_res.status_code == 200
    assert me_res.json()["username"] == "login_user"


def test_login_invalid_password_fails(client):
    res = client.post(
        "/api/auth/login",
        json={"username": "login_user", "password": "WrongPassword!"},
    )
    assert res.status_code == 401
