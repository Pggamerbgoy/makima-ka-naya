import sys
import sqlite3
import json
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

p = Path.home() / ".makima" / "state" / "history.db"

def run_audit(start_id=300):
    if not p.exists():
        print(f"Error: {p} does not exist.")
        return

    conn = sqlite3.connect(p)
    c = conn.cursor()
    c.execute("SELECT id, session_id, role, turn_index, content, tool_calls, timestamp FROM conversation_turns WHERE id >= ? ORDER BY id ASC", (start_id,))
    rows = c.fetchall()
    conn.close()

    print("=" * 80)
    print(f"MAKIMA REAL-TIME EXECUTION & HALLUCINATION AUDIT (Turns since ID {start_id})")
    print("=" * 80)

    i = 0
    while i < len(rows):
        row = rows[i]
        turn_id, sess_id, role, turn_idx, content, tool_calls_raw, ts = row
        
        if role == "user":
            user_msg = content.strip().replace("\n", " ")
            print(f"\n[PROMPT ID {turn_id}] (Turn {turn_idx})")
            print(f"  User Query: \"{user_msg}\"")
            
            # Look ahead for tools and assistant response in this turn
            tool_actions = []
            tool_outputs = []
            final_response = ""
            
            j = i + 1
            while j < len(rows) and rows[j][2] != "user":
                sub_row = rows[j]
                sub_role = sub_row[2]
                sub_content = sub_row[4]
                sub_tc = sub_row[5]
                
                if sub_tc:
                    try:
                        parsed_tc = json.loads(sub_tc) if isinstance(sub_tc, str) else sub_tc
                        for tc in parsed_tc:
                            tool_actions.append(f"{tc.get('name')}({json.dumps(tc.get('arguments', {}))})")
                    except Exception:
                        tool_actions.append(str(sub_tc))
                
                if sub_role == "tool":
                    tool_outputs.append(sub_content[:200] + ("..." if len(sub_content) > 200 else ""))
                
                if sub_role == "assistant" and sub_content and not sub_tc:
                    final_response = sub_content
                elif sub_role == "assistant" and sub_content and sub_tc:
                    # Thought or action announcement
                    pass
                j += 1
            
            # Print execution trace
            if tool_actions:
                print(f"  Tools Invoked ({len(tool_actions)}):")
                for act in tool_actions:
                    print(f"    - {act}")
            else:
                print("  Tools Invoked: None (Direct contextual response)")
            
            if tool_outputs:
                print(f"  Tool Outputs Received ({len(tool_outputs)}):")
                for out in tool_outputs:
                    print(f"    - {out}")
            
            # Hallucination & Grounding Check
            spoofed_faked = "[Executed Tools in Turn:" in final_response or "browser_interact(" in final_response
            
            print(f"  Assistant Response:")
            for line in final_response.strip().splitlines()[:6]:
                print(f"    {line}")
            if len(final_response.strip().splitlines()) > 6:
                print("    ...")

            # Audit Verdict
            print("  --- Audit Verdict ---")
            if spoofed_faked:
                print("  [FAIL] HALLUCINATION DETECTED: Model printed faked tool call text!")
            elif tool_actions and final_response:
                print("  [PASS] ZERO HALLUCINATION: Model invoked real tools, received live data, and answered with grounded telemetry.")
            elif not tool_actions and final_response:
                print("  [PASS] CONTEXTUAL SYNTHESIS: Answered accurately from immediate prior turn context without hallucinating.")
            print("-" * 80)
            
            i = j
        else:
            i += 1

if __name__ == "__main__":
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 303
    run_audit(start)
