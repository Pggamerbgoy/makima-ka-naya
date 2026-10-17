import sqlite3
from pathlib import Path
import json

state_dir = Path.home() / ".makima" / "state"

def inspect_recent_turns():
    db_path = state_dir / "history.db"
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM conversation_turns ORDER BY id DESC LIMIT 5")
    cols = [d[0] for d in cursor.description]
    print(f"\n--- Recent from conversation_turns in history.db ---")
    for r in cursor.fetchall():
        d = dict(zip(cols, r))
        print(f"ID: {d.get('id')} | Session: {d.get('session_id')} | Role: {d.get('role')} | Turn: {d.get('turn_index')}")
        content = str(d.get('content', ''))
        print(f"  Content ({len(content)} chars): {content[:200]}...")
        if 'tool_calls' in d:
            print(f"  Tool Calls: {d.get('tool_calls')}")
        print("-" * 60)
    conn.close()

def inspect_recent_sessions():
    db_path = state_dir / "sessions.sqlite3"
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM messages ORDER BY rowid DESC LIMIT 5")
    cols = [d[0] for d in cursor.description]
    print(f"\n--- Recent from messages in sessions.sqlite3 ---")
    for r in cursor.fetchall():
        d = dict(zip(cols, r))
        print(f"ID: {d.get('message_id')} | Role: {d.get('role')} | Created: {d.get('created_at')}")
        content = str(d.get('content', ''))
        print(f"  Content: {content[:200]}...")
        if d.get('metadata'):
            print(f"  Metadata: {d.get('metadata')}")
        print("-" * 60)
    conn.close()

if __name__ == "__main__":
    inspect_recent_turns()
    inspect_recent_sessions()
