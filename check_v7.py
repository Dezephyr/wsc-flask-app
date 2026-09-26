import sqlite3

conn = sqlite3.connect("data/wsc.sqlite")

u_cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
print("user columns:", u_cols)

tables = [r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'"
).fetchall()]
print("tables:", tables)

conn.close()