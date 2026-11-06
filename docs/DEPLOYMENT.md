# LedgerLine — Deployment Guide

> Step-by-step deployment guide for **Render**, **Railway**, and **Vercel** with **Neon PostgreSQL**.

---

## 1. Prerequisites
- A GitHub repository with your LedgerLine code pushed.
- A free account on [Render](https://render.com) (no credit card required).
- A free [Neon](https://neon.tech) serverless PostgreSQL database.

---

## 2. Deploying on Render (Free & Fast)

### Option A: 1-Click via `render.yaml`
1. Go to your [Render Dashboard](https://dashboard.render.com).
2. Click **New +** &rarr; **Blueprint**.
3. Connect your GitHub repository: `your-username/LedgerLine`.
4. Render will auto-detect the service configuration from `render.yaml`.
5. Under Environment Variables, ensure `DATABASE_URL` is set to your Neon pooled connection string.
6. Click **Apply**. Your app will build and go live at `https://<your-subdomain>.onrender.com`.

### Option B: Manual Web Service Setup
1. In the Render Dashboard, click **New +** &rarr; **Web Service**.
2. Select your repository.
3. Configure the following settings:
   - **Name**: `ledgerline`
   - **Region**: Oregon or Ohio (closest to your Neon database)
   - **Branch**: `main`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Add Environment Variables:
   - `DATABASE_URL`: Your Neon PostgreSQL connection string (e.g. `postgresql://...`)
   - `SECRET_KEY`: A random 32-character secret string (e.g. `generate-with-openssl-rand-hex-32`)
   - `DEBUG`: `False`
5. Click **Create Web Service**.

---

## 3. Database Initialization on Neon

LedgerLine features automated self-initialization. Upon the first startup on Render/Neon:
1. `Base.metadata.create_all(bind=engine)` automatically provisions all relational tables (`users`, `accounts`, `transactions`, `ledger_entries`, `idempotency_records`, `audit_logs`).
2. `AccountService.get_or_create_system_clearing_account()` provisions the system clearing reserve.
3. `AuthService.seed_initial_data()` creates default accounts for `admin`, `alice`, `bob`, and `auditor`.

---

## 4. Verifying the Live Deployment

Once deployed, verify the system in your browser or with `curl`:
1. **Health Check**:
   ```bash
   curl https://<your-render-url>.onrender.com/health
   # Expected: {"status":"healthy","application":"LedgerLine","version":"1.0.0"}
   ```
2. **Database Health**:
   ```bash
   curl https://<your-render-url>.onrender.com/health/database
   # Expected: {"database":"connected","status":"healthy"}
   ```
3. **Web Portal**:
   Open `https://<your-render-url>.onrender.com/login` in an **incognito browser tab** to confirm it loads cleanly for judges without authentication prerequisites.
