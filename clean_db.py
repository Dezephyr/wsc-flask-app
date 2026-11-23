"""
Wipes all user data except admin/support accounts.
Keeps: users with role='admin' or role='support', and their own KYC.
Deletes: all other users, all KYC submissions, transfers, bank links,
         loans, copy_traders, tickets, ticket replies, content pages,
         compliance docs, wallets, audit log.
"""
import sqlite3

conn = sqlite3.connect("data/wsc.sqlite")
conn.execute("PRAGMA foreign_keys = ON")

# Step 1 — find the admin/support user ids to keep
keep_ids = [
    row[0] for row in conn.execute(
        "SELECT id FROM users WHERE role IN ('admin', 'support')"
    ).fetchall()
]
print(f"Keeping {len(keep_ids)} admin/support account(s).")

if not keep_ids:
    print("WARNING: no admin accounts found. Aborting so you don't lock yourself out.")
    conn.close()
    raise SystemExit(1)

placeholders = ",".join("?" * len(keep_ids))

# Step 2 — delete child tables first (foreign key order)
deletes = [
    ("ticket_replies",         None),
    ("support_tickets",        None),
    ("compliance_documents",   None),
    ("content_pages",          None),
    ("copy_traders",           None),
    ("loans",                  None),
    ("transfers",              None),
    ("bank_links",             None),
    ("wallets",                None),  # ignore error if table doesn't exist
    ("kyc_submissions",        f"user_id NOT IN ({placeholders})"),
    ("audit_log",              None),
]

for table, where in deletes:
    try:
        if where:
            conn.execute(f"DELETE FROM {table} WHERE {where}", keep_ids)
        else:
            conn.execute(f"DELETE FROM {table}")
        print(f"  cleared: {table}")
    except sqlite3.OperationalError as e:
        # Table doesn't exist yet — skip
        print(f"  skipped: {table} ({e})")

# Step 3 — delete every user except admin/support
conn.execute(f"DELETE FROM users WHERE id NOT IN ({placeholders})", keep_ids)
print(f"  deleted non-admin users")

conn.commit()

# Step 4 — report what's left
remaining = conn.execute("SELECT email, role FROM users").fetchall()
print("\nRemaining accounts:")
for email, role in remaining:
    print(f"  {email}  [{role}]")

conn.close()
print("\nclean complete")
