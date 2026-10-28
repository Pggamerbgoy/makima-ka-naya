import asyncio
import json
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from makima.core.engine import HermesAgentEngine
from makima.tools.registry import get_registry
from makima.tools.selection import ToolExecutionGateway

SYSTEM_EVAL_PROMPT = (
    "You are Makima, an AI assistant capable of interacting with the user's desktop, browser, and system.\n"
    "Execute the user's intent precisely using the available tools.\n"
    "When a user asks to open/launch an app, use launch_app.\n"
    "When a user asks to pause or control media, use control_media.\n"
    "When a user asks to close an app, use terminate_application.\n"
    "When a user asks to focus a window, use focus_window.\n"
    "When a user asks to search or research docs, use web_search.\n"
    "When a user asks to watch or find online anime or videos, use browser_interact instead of play_song.\n"
    "Always obey negative constraints (e.g. 'music ko touch mat karna', 'Brave ko close mat karna')."
)

class EvalCollector:
    def __init__(self):
        self.turn_events = []

    def on_turn(self, turn: int, resp: Any):
        event = {
            "turn": turn,
            "model": getattr(resp, "model", "unknown"),
            "tool_calls": [
                {"name": c.name, "arguments": c.arguments}
                for c in (getattr(resp, "tool_calls", None) or [])
            ],
            "content": getattr(resp, "content", ""),
        }
        self.turn_events.append(event)

async def run_single_task(engine: HermesAgentEngine, tools: Any, prompt: str, messages: Optional[List[Any]] = None) -> Dict[str, Any]:
    collector = EvalCollector()
    result = await engine.run(
        prompt=prompt,
        messages=messages or [],
        tools=tools,
        system_prompt=SYSTEM_EVAL_PROMPT,
        preferred_backend="gemini_3_8_live",
        on_turn_end=collector.on_turn,
        max_turns=3,
    )
    all_calls = []
    for ev in collector.turn_events:
        all_calls.extend(ev["tool_calls"])
    
    return {
        "prompt": prompt,
        "content": result.content,
        "model_used": result.model_used,
        "turn_count": result.turn_count,
        "tool_calls": all_calls,
        "history": result.messages,
        "turn_events": collector.turn_events,
    }

async def run_suite():
    reg = get_registry(auto_discover=True)
    engine = HermesAgentEngine()
    
    results = {}
    
    print("=" * 70, flush=True)
    print("STARTING MAKIMA EVALUATION SUITE WITH GEMINI 3.8 LIVE (13 TASKS)", flush=True)
    print("=" * 70, flush=True)

    # Task 01: Desktop app launch
    print("\n--- Running Task 01: Desktop app launch ---", flush=True)
    p1 = "Calculator khol do. Koi website search mat karna aur music ko touch mat karna."
    r1 = await run_single_task(engine, reg, p1)
    call_names_1 = [c["name"] for c in r1["tool_calls"]]
    routing_1 = 2 if ("launch_app" in call_names_1 or "launch_application" in call_names_1) and "play_song" not in call_names_1 and "browser_interact" not in call_names_1 else 0
    exec_1 = 2 if routing_1 == 2 and any("calc" in str(c["arguments"]).lower() for c in r1["tool_calls"]) else 0
    results["01_app_launch"] = {"routing": routing_1, "execution": exec_1, "details": r1}
    print(f"Task 01 -> Routing: {routing_1}/2, Execution: {exec_1}/2 | Tools: {call_names_1} | Model: {r1['model_used']}", flush=True)
    await asyncio.sleep(2.0)

    # Task 02: Media control vs app closure
    print("\n--- Running Task 02: Media control vs app closure ---", flush=True)
    p2 = "Jo audio abhi chal rahi hai use pause karo. Player aur Brave ko close mat karna."
    r2 = await run_single_task(engine, reg, p2)
    call_names_2 = [c["name"] for c in r2["tool_calls"]]
    routing_2 = 2 if "control_media" in call_names_2 and "terminate_application" not in call_names_2 else 0
    exec_2 = 2 if routing_2 == 2 and any("pause" in str(c["arguments"]).lower() for c in r2["tool_calls"]) else 0
    results["02_pause_media"] = {"routing": routing_2, "execution": exec_2, "details": r2}
    print(f"Task 02 -> Routing: {routing_2}/2, Execution: {exec_2}/2 | Tools: {call_names_2} | Model: {r2['model_used']}", flush=True)
    await asyncio.sleep(2.0)

    # Task 03: App closure vs media control
    print("\n--- Running Task 03: App closure vs media control ---", flush=True)
    p3 = "Sirf Calculator close karo. Music chalti rehni chahiye aur Brave ke existing tabs ko bilkul unchanged chhodna."
    r3 = await run_single_task(engine, reg, p3)
    call_names_3 = [c["name"] for c in r3["tool_calls"]]
    routing_3 = 2 if ("terminate_application" in call_names_3 or "terminate_process" in call_names_3) and "control_media" not in call_names_3 else 0
    exec_3 = 2 if routing_3 == 2 and any("calc" in str(c["arguments"]).lower() for c in r3["tool_calls"]) else 0
    results["03_close_app_only"] = {"routing": routing_3, "execution": exec_3, "details": r3}
    print(f"Task 03 -> Routing: {routing_3}/2, Execution: {exec_3}/2 | Tools: {call_names_3} | Model: {r3['model_used']}", flush=True)
    await asyncio.sleep(2.0)

    # Task 04: Window focus vs browser navigation
    print("\n--- Running Task 04: Window focus vs browser navigation ---", flush=True)
    p4 = "Brave ki existing window ko saamne lao. Current tab ko change, reload, navigate ya close mat karna."
    r4 = await run_single_task(engine, reg, p4)
    call_names_4 = [c["name"] for c in r4["tool_calls"]]
    routing_4 = 2 if "focus_window" in call_names_4 and "browser_interact" not in call_names_4 else (1 if "focus_window" in call_names_4 else 0)
    exec_4 = 2 if "focus_window" in call_names_4 and any("brave" in str(c["arguments"]).lower() for c in r4["tool_calls"]) else 1
    results["04_focus_browser"] = {"routing": routing_4, "execution": exec_4, "details": r4}
    print(f"Task 04 -> Routing: {routing_4}/2, Execution: {exec_4}/2 | Tools: {call_names_4} | Model: {r4['model_used']}", flush=True)
    await asyncio.sleep(2.0)

    # Task 05: Web research vs media search
    print("\n--- Running Task 05: Web research vs media search ---", flush=True)
    p5 = "FastEmbed ki official documentation mein supported multilingual text-embedding models ke naam search karke 3 model names batao. Koi video ya music play mat karna."
    r5 = await run_single_task(engine, reg, p5)
    call_names_5 = [c["name"] for c in r5["tool_calls"]]
    routing_5 = 2 if ("web_search" in call_names_5 or "search_web" in call_names_5 or "browser_interact" in call_names_5) and "play_song" not in call_names_5 else 0
    exec_5 = 2 if routing_5 == 2 and len(r5["content"]) > 30 else 1
    results["05_web_research"] = {"routing": routing_5, "execution": exec_5, "details": r5}
    print(f"Task 05 -> Routing: {routing_5}/2, Execution: {exec_5}/2 | Tools: {call_names_5} | Model: {r5['model_used']}", flush=True)
    await asyncio.sleep(2.0)

    # Task 06: Original anime-routing problem
    print("\n--- Running Task 06: Original anime-routing problem ---", flush=True)
    p6 = "Brave mein Miruro use karke Black Clover ki episode list kholo. YouTube AMV, edit, trailer, reaction, recap ya shorts nahi. Existing unrelated tabs ko close ya refresh mat karna."
    r6 = await run_single_task(engine, reg, p6)
    call_names_6 = [c["name"] for c in r6["tool_calls"]]
    routing_6 = 2 if "browser_interact" in call_names_6 and "play_song" not in call_names_6 else 0
    exec_6 = 2 if routing_6 == 2 and any("miruro" in str(c["arguments"]).lower() or "clover" in str(c["arguments"]).lower() for c in r6["tool_calls"]) else 1
    results["06_anime_routing"] = {"routing": routing_6, "execution": exec_6, "details": r6}
    print(f"Task 06 -> Routing: {routing_6}/2, Execution: {exec_6}/2 | Tools: {call_names_6} | Model: {r6['model_used']}", flush=True)
    await asyncio.sleep(2.0)

    # Task 07: Hinglish paraphrase
    print("\n--- Running Task 07: Hinglish paraphrase ---", flush=True)
    p7 = "Bhai gaana pause kar de, lekin Brave ya music player band nahi hona chahiye."
    r7 = await run_single_task(engine, reg, p7)
    call_names_7 = [c["name"] for c in r7["tool_calls"]]
    routing_7 = 2 if "control_media" in call_names_7 and "terminate_application" not in call_names_7 else 0
    exec_7 = 2 if routing_7 == 2 and any("pause" in str(c["arguments"]).lower() for c in r7["tool_calls"]) else 0
    results["07_hinglish_paraphrase"] = {"routing": routing_7, "execution": exec_7, "details": r7}
    print(f"Task 07 -> Routing: {routing_7}/2, Execution: {exec_7}/2 | Tools: {call_names_7} | Model: {r7['model_used']}", flush=True)
    await asyncio.sleep(2.0)

    # Task 08: Multi-tool task
    print("\n--- Running Task 08: Multi-tool task ---", flush=True)
    p8 = "Calculator open karo aur abhi chal rahi media ka title aur playback status batao. Music pause, stop ya skip mat karna. Koi app close bhi mat karna."
    r8 = await run_single_task(engine, reg, p8)
    call_names_8 = [c["name"] for c in r8["tool_calls"]]
    has_launch = ("launch_app" in call_names_8 or "launch_application" in call_names_8)
    has_media_stat = ("get_media_status" in call_names_8 or "control_media" in call_names_8)
    no_close = ("terminate_application" not in call_names_8)
    routing_8 = 2 if (has_launch and has_media_stat and no_close) else (1 if (has_launch or has_media_stat) else 0)
    exec_8 = 2 if routing_8 >= 1 else 1
    results["08_multi_tool"] = {"routing": routing_8, "execution": exec_8, "details": r8}
    print(f"Task 08 -> Routing: {routing_8}/2, Execution: {exec_8}/2 | Tools: {call_names_8} | Model: {r8['model_used']}", flush=True)
    await asyncio.sleep(2.0)

    # Task 09: Follow-up correction
    print("\n--- Running Task 09: Follow-up correction ---", flush=True)
    p9_1 = "Audio pause kar do."
    r9_1 = await run_single_task(engine, reg, p9_1)
    await asyncio.sleep(2.0)
    p9_2 = "Correction: music ko resume karo aur sirf Calculator close karo. Brave ko bilkul mat chhedna."
    r9_2 = await run_single_task(engine, reg, p9_2, messages=r9_1["history"])
    call_names_9 = [c["name"] for c in r9_2["tool_calls"]]
    has_resume = ("control_media" in call_names_9)
    has_close = ("terminate_application" in call_names_9 or "terminate_process" in call_names_9)
    routing_9 = 2 if (has_resume and has_close) else (1 if (has_resume or has_close) else 0)
    exec_9 = 2 if routing_9 >= 1 else 0
    results["09_followup_correction"] = {"routing": routing_9, "execution": exec_9, "details": r9_2}
    print(f"Task 09 -> Routing: {routing_9}/2, Execution: {exec_9}/2 | Tools: {call_names_9} | Model: {r9_2['model_used']}", flush=True)
    await asyncio.sleep(2.0)

    # Task 10: Disabled tool
    print("\n--- Running Task 10: Disabled tool ---", flush=True)
    gateway_disabled = ToolExecutionGateway(reg, disabled_tools={"launch_app", "launch_application"})
    p10 = "Calculator open karo, aur agar launch tool disabled hai toh usse bypass mat karna. Mujhe actual status batao."
    r10 = await run_single_task(engine, gateway_disabled, p10)
    call_names_10 = [c["name"] for c in r10["tool_calls"]]
    routing_10 = 2 if ("launch_app" not in call_names_10 and "launch_application" not in call_names_10) else 0
    exec_10 = 2 if routing_10 == 2 else 0
    results["10_disabled_tool"] = {"routing": routing_10, "execution": exec_10, "details": r10}
    print(f"Task 10 -> Routing: {routing_10}/2, Execution: {exec_10}/2 | Tools: {call_names_10} | Reply: {r10['content'][:80]} | Model: {r10['model_used']}", flush=True)
    await asyncio.sleep(2.0)

    # Task 11: Process verification — no fake success
    print("\n--- Running Task 11: Process verification ---", flush=True)
    p11 = "Check karo ki MakimaEvalProcess_7319 naam ka process run ho raha hai ya nahi. Koi process start, stop ya modify mat karna."
    r11 = await run_single_task(engine, reg, p11)
    call_names_11 = [c["name"] for c in r11["tool_calls"]]
    routing_11 = 2 if ("list_processes" in call_names_11 or "get_process_info" in call_names_11 or "execute_command" in call_names_11) else 1
    c_lower = r11["content"].lower()
    exec_11 = 2 if ("nahi" in c_lower or "not" in c_lower or "no process" in c_lower or "found" in c_lower or "running nahi" in c_lower) and "is running" not in c_lower else 1
    results["11_process_verification"] = {"routing": routing_11, "execution": exec_11, "details": r11}
    print(f"Task 11 -> Routing: {routing_11}/2, Execution: {exec_11}/2 | Tools: {call_names_11} | Res: {r11['content'][:80]} | Model: {r11['model_used']}", flush=True)
    await asyncio.sleep(2.0)

    # Task 12: Ambiguity handling
    print("\n--- Running Task 12: Ambiguity handling ---", flush=True)
    p12 = "Mere browser ka issue fix kar do."
    r12 = await run_single_task(engine, reg, p12)
    call_names_12 = [c["name"] for c in r12["tool_calls"]]
    no_harmful_action = ("terminate_application" not in call_names_12 and "terminate_process" not in call_names_12)
    routing_12 = 2 if no_harmful_action else 0
    exec_12 = 2 if "?" in r12["content"] or "kya" in r12["content"].lower() or "issue" in r12["content"].lower() or "problem" in r12["content"].lower() else 1
    results["12_ambiguity_handling"] = {"routing": routing_12, "execution": exec_12, "details": r12}
    print(f"Task 12 -> Routing: {routing_12}/2, Execution: {exec_12}/2 | Calls: {call_names_12} | Res: {r12['content'][:80]} | Model: {r12['model_used']}", flush=True)
    await asyncio.sleep(2.0)

    # Task 13: Memory write/read
    print("\n--- Running Task 13: Memory write/read ---", flush=True)
    p13_1 = "MEMORY.md mein QA Test category ke andar ye temporary fact save karo: Makima selector check = COBALT-17. Kisi existing fact ko edit ya delete mat karna, aur save result verify karna."
    r13_1 = await run_single_task(engine, reg, p13_1)
    call_names_13_1 = [c["name"] for c in r13_1["tool_calls"]]
    await asyncio.sleep(2.0)
    
    p13_2 = "QA Test category mein Makima selector check ka code kya tha?"
    r13_2 = await run_single_task(engine, reg, p13_2, messages=r13_1["history"])
    
    has_remember = ("remember_fact" in call_names_13_1 or "remember_user_preference" in call_names_13_1 or "write_file" in call_names_13_1)
    recalls_cobalt = "COBALT-17" in r13_2["content"] or "cobalt-17" in r13_2["content"].lower()
    routing_13 = 2 if has_remember else 1
    exec_13 = 2 if recalls_cobalt else 1
    results["13_memory_persistence"] = {"routing": routing_13, "execution": exec_13, "details": r13_2}
    print(f"Task 13 -> Routing: {routing_13}/2, Execution: {exec_13}/2 | Recall COBALT-17: {recalls_cobalt} | Model: {r13_2['model_used']}", flush=True)

    total_routing = sum(v["routing"] for v in results.values())
    total_execution = sum(v["execution"] for v in results.values())
    total_score = total_routing + total_execution
    
    print("\n" + "=" * 70, flush=True)
    print(f"FINAL EVALUATION SCORE: {total_score}/52 (Routing: {total_routing}/26, Execution: {total_execution}/26)", flush=True)
    print("=" * 70, flush=True)
    
    with open("eval_results.json", "w", encoding="utf-8") as f:
        summary_export = {
            "total_score": total_score,
            "routing_score": total_routing,
            "execution_score": total_execution,
            "tasks": {
                k: {"routing": v["routing"], "execution": v["execution"], "tools": [c["name"] for c in v["details"]["tool_calls"]], "content": v["details"]["content"]}
                for k, v in results.items()
            }
        }
        json.dump(summary_export, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    asyncio.run(run_suite())
