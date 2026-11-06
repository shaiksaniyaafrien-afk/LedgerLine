
import os
from pathlib import Path

from dotenv import load_dotenv

# Locate the root LedgerLine directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load environment variables from the project root
load_dotenv(BASE_DIR / ".env")


class Settings:
    PROJECT_NAME = "LedgerLine"
    PROJECT_VERSION = "1.0.0"
    PROJECT_DESCRIPTION = "Secure Digital Banking and Ledger Management System"

    @property
    def TESTING(self) -> bool:
        return os.getenv("TESTING", "False").lower() == "true"

    @property
    def DATABASE_URL(self) -> str:
        if self.TESTING:
            return "sqlite:///:memory:"
        return os.getenv("DATABASE_URL") or "sqlite:///./ledgerline.db"

    DATABASE_URL_UNPOOLED = os.getenv("DATABASE_URL_UNPOOLED")

    SECRET_KEY = os.getenv("SECRET_KEY", "development-only-change-this-key")
    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = 60

    DEBUG = os.getenv("DEBUG", "False").lower() == "true"


settings = Settings()
