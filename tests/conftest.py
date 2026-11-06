import os
import pytest
from decimal import Decimal
from fastapi.testclient import TestClient

from app.core.database import Base, engine, SessionLocal, get_db

TestingSessionLocal = SessionLocal
from app.main import app
from app.models.user import User, UserRole
from app.models.account import Account, AccountType, AccountStatus
from app.core.security import hash_password, create_access_token
from app.services.account_service import AccountService


@pytest.fixture(scope="session", autouse=True)
def init_test_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    AccountService.get_or_create_system_clearing_account(db)
    db.close()
    yield
    # Cleanup after session
    Base.metadata.drop_all(bind=engine)
    if os.path.exists("./ledgerline_test.db"):
        try:
            os.remove("./ledgerline_test.db")
        except Exception:
            pass


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def test_users(db):
    admin = db.query(User).filter(User.username == "test_admin").first()
    if not admin:
        admin = User(
            username="test_admin",
            email="admin@test.com",
            hashed_password=hash_password("Pass123!"),
            full_name="Admin User",
            role=UserRole.ADMIN,
        )
        db.add(admin)

    auditor = db.query(User).filter(User.username == "test_auditor").first()
    if not auditor:
        auditor = User(
            username="test_auditor",
            email="auditor@test.com",
            hashed_password=hash_password("Pass123!"),
            full_name="Auditor User",
            role=UserRole.AUDITOR,
        )
        db.add(auditor)

    alice = db.query(User).filter(User.username == "test_alice").first()
    if not alice:
        alice = User(
            username="test_alice",
            email="alice@test.com",
            hashed_password=hash_password("Pass123!"),
            full_name="Alice User",
            role=UserRole.ACCOUNT_HOLDER,
        )
        db.add(alice)

    bob = db.query(User).filter(User.username == "test_bob").first()
    if not bob:
        bob = User(
            username="test_bob",
            email="bob@test.com",
            hashed_password=hash_password("Pass123!"),
            full_name="Bob User",
            role=UserRole.ACCOUNT_HOLDER,
        )
        db.add(bob)
    db.commit()

    db.refresh(admin)
    db.refresh(auditor)
    db.refresh(alice)
    db.refresh(bob)

    alice_acc = db.query(Account).filter(Account.account_number == "ACC-ALICE-TEST").first()
    if not alice_acc:
        alice_acc = AccountService.create_account(
            db=db,
            user_id=alice.id,
            account_number="ACC-ALICE-TEST",
            initial_deposit=Decimal("1000.0000"),
            currency="INR",
        )

    bob_acc = db.query(Account).filter(Account.account_number == "ACC-BOB-TEST").first()
    if not bob_acc:
        bob_acc = AccountService.create_account(
            db=db,
            user_id=bob.id,
            account_number="ACC-BOB-TEST",
            initial_deposit=Decimal("500.0000"),
            currency="INR",
        )
    db.commit()

    db.refresh(alice_acc)
    db.refresh(bob_acc)

    return {
        "admin": admin,
        "auditor": auditor,
        "alice": alice,
        "bob": bob,
        "alice_acc": alice_acc,
        "bob_acc": bob_acc,
    }


def get_token_for(user: User) -> str:
    return create_access_token({"sub": user.username, "user_id": user.id, "role": user.role.value})
