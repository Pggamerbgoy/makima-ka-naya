import sqlite3
from pathlib import Path

p = Path.home() / ".makima" / "state" / "history.db"
conn = sqlite3.connect(p)
c = conn.cursor()
c.execute("SELECT id, session_id, role, turn_index, content, tool_calls FROM conversation_turns WHERE id >= 300 ORDER BY id ASC")
cols = [d[0] for d in c.description]
for r in c.fetchall():
    d = dict(zip(cols, r))
    tc = d.get("tool_calls")
    content = str(d.get("content", ""))[:120].replace("\n", " ")
    print(f"ID: {d.get('id')} | Role: {d.get('role')} | Turn: {d.get('turn_index')} | Tools: {tc[:60] if tc else None}")
    print(f"   Content: {content}")
    print("-" * 50)
conn.close()
