"""
One-off: print every non-regular user and their role.
Run from the project root:  python check_admins.py
"""
from app.db import get_db

conn = get_db()
rows = conn.execute(
    "SELECT id, email, role FROM users WHERE role != 'user';"
).fetchall()
conn.close()

if not rows:
    print("No admin/support users found. Every account is role='user'.")
else:
    print(f"Found {len(rows)} admin/support user(s):\n")
    for r in rows:
        print(f"  id:    {r['id']}")
        print(f"  email: {r['email']}")
        print(f"  role:  {r['role']!r}")   # !r shows quotes so you can see whitespace
        print()