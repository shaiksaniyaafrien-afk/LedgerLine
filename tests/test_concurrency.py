import concurrent.futures
from decimal import Decimal
from tests.conftest import get_token_for, TestingSessionLocal
from app.models.account import Account, AccountType, AccountStatus
from app.services.account_service import AccountService


def test_concurrent_withdrawals_cannot_overdraw(client, test_users):
    """
    Simulates race condition attack:
    An account has 200.00 balance.
    10 threads concurrently fire requests to withdraw 100.00 each at the exact same millisecond.
    Total attempted withdrawal: 1,000.00.
    Available balance: 200.00.

    Requirement:
    Exactly 2 requests must succeed.
    Exactly 8 requests must be refused with 400 Insufficient Funds.
    Final balance MUST be exactly 0.00, never negative!
    """
    db = TestingSessionLocal()
    alice = test_users["alice"]
    # Create a fresh isolated account with exactly 200.00 via proper deposit
    race_acc = AccountService.create_account(
        db=db,
        user_id=alice.id,
        account_number="ACC-RACE-TEST-1",
        initial_deposit=Decimal("200.0000"),
        currency="INR",
    )
    race_acc_id = race_acc.id
    db.close()

    token = get_token_for(alice)

    def attempt_withdrawal(thread_idx):
        return client.post(
            "/api/transactions/withdraw",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "account_id": race_acc_id,
                "amount": 100.0,
                "description": f"Race withdrawal thread #{thread_idx}",
            },
        )

    # Fire 10 concurrent requests simultaneously using thread pool
    num_threads = 10
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(attempt_withdrawal, i) for i in range(num_threads)]
        responses = [f.result() for f in concurrent.futures.as_completed(futures)]

    success_count = sum(1 for r in responses if r.status_code == 200)
    refused_count = sum(1 for r in responses if r.status_code == 400)

    # Exactly 2 can succeed since 2 * 100 = 200
    assert success_count == 2, f"Expected exactly 2 successes, got {success_count}"
    assert refused_count == 8, f"Expected exactly 8 refused attempts, got {refused_count}"

    # Verify final balance is exactly zero
    final_res = client.get(
        f"/api/accounts/{race_acc_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert final_res.status_code == 200
    final_balance = float(final_res.json()["balance"])
    assert final_balance == 0.0, f"Balance was driven negative! Current balance: {final_balance}"


def test_concurrent_bidirectional_transfers_conserve_total(client, test_users):
    """
    Tests concurrency & deadlock safety during heavy cross transfers:
    Account X (500) and Account Y (500). Total = 1000.
    20 concurrent threads randomly transferring back and forth between X and Y.
    Zero deadlocks occur due to deterministic row lock ordering.
    Total money in system across X and Y after all transfers equals exactly 1000.00.
    """
    db = TestingSessionLocal()
    alice = test_users["alice"]
    bob = test_users["bob"]

    acc_x = AccountService.create_account(
        db=db,
        user_id=alice.id,
        account_number="ACC-X-CONCUR",
        initial_deposit=Decimal("500.0000"),
        currency="INR",
    )
    acc_y = AccountService.create_account(
        db=db,
        user_id=bob.id,
        account_number="ACC-Y-CONCUR",
        initial_deposit=Decimal("500.0000"),
        currency="INR",
    )

    x_id = acc_x.id
    x_num = acc_x.account_number
    y_id = acc_y.id
    y_num = acc_y.account_number
    db.close()

    alice_token = get_token_for(alice)
    bob_token = get_token_for(bob)

    def send_x_to_y(i):
        return client.post(
            "/api/transactions/transfer",
            headers={"Authorization": f"Bearer {alice_token}"},
            json={
                "source_account_id": x_id,
                "destination_account_number": y_num,
                "amount": 20.0,
                "description": f"X->Y #{i}",
            },
        )

    def send_y_to_x(i):
        return client.post(
            "/api/transactions/transfer",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={
                "source_account_id": y_id,
                "destination_account_number": x_num,
                "amount": 20.0,
                "description": f"Y->X #{i}",
            },
        )

    # 10 transfers X->Y and 10 transfers Y->X executing concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        f_xy = [executor.submit(send_x_to_y, i) for i in range(10)]
        f_yx = [executor.submit(send_y_to_x, i) for i in range(10)]
        all_futures = f_xy + f_yx
        results = [f.result() for f in concurrent.futures.as_completed(all_futures)]

    # Check for no 500 errors (no unhandled database deadlocks)
    for r in results:
        assert r.status_code in [200, 400], f"Unexpected error: {r.status_code} {r.text}"

    # Read final balances
    x_res = client.get(f"/api/accounts/{x_id}", headers={"Authorization": f"Bearer {alice_token}"})
    y_res = client.get(f"/api/accounts/{y_id}", headers={"Authorization": f"Bearer {bob_token}"})
    bal_x = float(x_res.json()["balance"])
    bal_y = float(y_res.json()["balance"])

    assert bal_x >= 0.0
    assert bal_y >= 0.0
    assert round(bal_x + bal_y, 4) == 1000.0, f"Money created or lost! Sum: {bal_x + bal_y}"
