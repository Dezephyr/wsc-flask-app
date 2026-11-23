# Wall Street Capital — Flask backend

Same scaffold as before, rebuilt on Flask instead of Node/Express. Identity
verification, custody of funds, and trade execution still all happen at a
licensed third party (Alpaca's Broker API), never inside this app.

## What this does and doesn't do

**Does:**
- Standard auth (Werkzeug password hashing + JWT), user profiles
- KYC intake form that submits to Alpaca's Broker API for the actual
  identity-verification decision
- A dashboard that reads real account/positions data from Alpaca — the 3D
  chart's bar heights come directly from that data
- Bank-account linking via Plaid, ACH deposits/withdrawals via Alpaca's
  Transfers API
- An admin panel for content, compliance-document metadata, support tickets,
  and viewing the KYC queue

**Does not do, on purpose:**
- Store or move money itself — every dollar movement is a call to Alpaca's
  Transfers API; this app never increments a balance
- Let an admin edit a balance, approve their own KYC, or fabricate a transfer
- Generate or simulate trading returns — there is no "bot" here. Numbers
  either come from Alpaca or they don't appear

## Why Flask over the Node version

Functionally identical — same routes, same database schema, same frontend.
The main practical difference: this version has no native/compiled
dependencies (no `better-sqlite3`, no `bcrypt`), which sidesteps the
Windows build-tools issues those can cause. Python's built-in `sqlite3`
module and Werkzeug's password hashing need no compilation.

## Before this can go live

1. **Get approved for Alpaca's Broker API** — this is a partnership product,
   not a self-serve API key. See https://alpaca.markets/broker. Until
   you're approved, `ALPACA_BROKER_API_KEY`/`SECRET` won't exist and every
   Alpaca-backed feature fails gracefully (KYC saves locally as
   "pending_review", portfolio shows "no_account").
2. **Get a Plaid account** approved for the "auth" + Alpaca-processor use
   case: https://plaid.com/docs/
3. **Talk to a securities/compliance lawyer** about registration and
   disclosure obligations before accepting real customers.
4. **Move off SQLite/dev server for production**: Postgres, a real WSGI
   server (gunicorn/uwsgi behind nginx), a secrets manager instead of
   `.env`, and an HttpOnly session cookie instead of a `localStorage` JWT.
5. **Encrypt KYC PII at rest** or, better, don't store more of it locally
   than a status flag — let Alpaca be the system of record for identity
   data. Route ID-document uploads through Alpaca's own document endpoints
   or a dedicated KYC vendor, not local disk.
6. **Add real content**: privacy policy, terms, Form ADV/CRS or your
   jurisdiction's equivalent, fee schedule — editable through the admin CMS
   once written.

## Running it locally

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env          # Windows: copy .env.example .env
# open .env and set JWT_SECRET to any long random string

python run.py
```

Then visit `http://localhost:4000` in Chrome.

To make your first admin user, sign up normally through the UI, then run:

```bash
python -c "
import sqlite3
conn = sqlite3.connect('data/wsc.sqlite')
conn.execute(\"UPDATE users SET role = 'admin' WHERE email = ?\", ('you@example.com',))
conn.commit()
"
```

Log out and back in, then visit `http://localhost:4000/admin/index.html`.

## Project layout

```
run.py                  Entry point (python run.py)
app/
  __init__.py           App factory: registers blueprints, static files, rate limiting
  db.py                 SQLite schema (see comments — no balance-mutation tables)
  auth.py               Password hashing, JWT issue/verify, route decorators
  services/
    alpaca_broker.py    Account opening, ACH relationships, transfers, positions
    plaid_client.py     Bank-account linking -> processor token for Alpaca
  routes/
    auth_routes.py      signup / login / me
    kyc_routes.py        KYC intake -> Alpaca account creation
    banking_routes.py    Plaid link + Alpaca ACH relationship + transfers
    portfolio_routes.py  Read-only account + positions from Alpaca
    admin_routes.py      Content CMS, compliance docs, KYC queue, tickets
    support_routes.py    User-facing support tickets

public/                 Same frontend as the Node version — untouched
  index.html, login.html, signup.html, kyc.html, dashboard.html
  admin/index.html
  js/three-bg.js, portfolio-3d.js, api.js
  css/styles.css
```
