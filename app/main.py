import os
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.config import settings
from app.core.database import engine, Base, SessionLocal, check_database_connection, is_test_environment
from app.api import auth_router, accounts_router, transactions_router, audit_router
from app.services.auth_service import AuthService
from app.services.account_service import AccountService

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "app" / "templates"
STATIC_DIR = BASE_DIR / "static"

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Only perform auto-migration and cloud seeding when not running test suites
    if not is_test_environment():
        try:
            Base.metadata.create_all(bind=engine)
            db = SessionLocal()
            try:
                AccountService.get_or_create_system_clearing_account(db)
                AuthService.seed_initial_data(db)
            finally:
                db.close()
        except Exception:
            pass

    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.PROJECT_VERSION,
    description=settings.PROJECT_DESCRIPTION,
    debug=settings.DEBUG,
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static and Templates
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Register API Routers
app.include_router(auth_router)
app.include_router(accounts_router)
app.include_router(transactions_router)
app.include_router(audit_router)


# Frontend Web Routes
@app.get("/", response_class=HTMLResponse)
def index_page():
    return RedirectResponse(url="/login")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})


@app.get("/auditor", response_class=HTMLResponse)
def auditor_page(request: Request):
    return templates.TemplateResponse("auditor.html", {"request": request})


@app.get("/statement", response_class=HTMLResponse)
def statement_page(request: Request):
    return templates.TemplateResponse("statement.html", {"request": request})


# Health & Info Endpoints
@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "application": settings.PROJECT_NAME,
        "version": settings.PROJECT_VERSION,
    }


@app.get("/health/database")
def database_health_check():
    connected = check_database_connection()
    return {
        "database": "connected" if connected else "disconnected",
        "status": "healthy" if connected else "unhealthy",
    }
