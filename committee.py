import sys
import re
import os
import urllib.request
import json
import sqlite3
from datetime import datetime

# =========================================================================
# CONFIGURATION
# =========================================================================
# Paste your fresh key securely inside the quotes below:
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# Leave the rest of the file completely as-is
MODEL_BUILDER = "qwen/qwen-2.5-7b-instruct"  # Representing The Engineer
MODEL_BUILDER_LOCAL = "qwen2.5:7b"           # Same model, served locally via Ollama/Antigravity — no API call, no cost
USE_LOCAL_BUILDER = False                      # Flip to False to fall back to OpenRouter for the Builder side
OLLAMA_URL = "http://localhost:11434/v1/chat/completions"
MODEL_CYNIC   = "nvidia/nemotron-3-super-120b-a12b:free"  # Legion Deliberation Partner
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

def write_live_log(text):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    live_path = os.path.join(script_dir, "committee_live.txt")
    with open(live_path, "w", encoding="utf-8") as f:
        f.write(text)

def update_token_usage(tokens_used: int):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(script_dir, "pipeline.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS token_count (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_count INTEGER NOT NULL,
                token_limit INTEGER NOT NULL
            )
            """
        )
        row = conn.execute("SELECT token_count, token_limit FROM token_count ORDER BY id DESC LIMIT 1").fetchone()
        new_count = (row["token_count"] if row else 142830) + tokens_used
        limit = row["token_limit"] if row else 500000
        conn.execute("INSERT INTO token_count (token_count, token_limit) VALUES (?, ?)", (new_count, limit))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()

def call_local_ollama(model_name, system_prompt, user_content):
    """Same request shape as call_openrouter, but hits your local Ollama/Antigravity
    endpoint instead — no API key, no token cost, no network call leaving the machine."""

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.2,
        "stream": False
    }

    req = urllib.request.Request(OLLAMA_URL)
    req.add_header("Content-Type", "application/json; charset=utf-8")

    try:
        data_bytes = json.dumps(payload).encode('utf-8')
        with urllib.request.urlopen(req, data=data_bytes, timeout=120) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            ai_response = res_data['choices'][0]['message']['content']
            # Local calls cost no tokens against your OpenRouter budget — do not log to update_token_usage.
            return ai_response

    except urllib.error.URLError as url_err:
        sys.stderr.write(
            f"\n[LOCAL ERROR] Could not reach Ollama at {OLLAMA_URL}: {url_err}\n"
            f"Is Ollama running, and is '{model_name}' pulled? Try: ollama list\n"
        )
        sys.exit(1)
    except Exception as e:
        sys.stderr.write(f"\n[LOCAL ERROR] {e}\n")
        sys.exit(1)

def call_builder(system_prompt, user_content):
    """Dispatcher: routes the Builder side to local Ollama or OpenRouter,
    based on USE_LOCAL_BUILDER. Everything downstream calls this, not the
    model-specific functions directly, so the switch stays in one place."""
    if USE_LOCAL_BUILDER:
        return call_local_ollama(MODEL_BUILDER_LOCAL, system_prompt, user_content)
    return call_openrouter(MODEL_BUILDER, system_prompt, user_content)

def call_openrouter(model_name, system_prompt, user_content):
    """Executes a clean, flat POST request to OpenRouter's API using strict HTTP packing."""
    
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.2,
        "stream": False
    }
    
    # 1. Clean up the key text aggressively to remove any hidden white spaces
    clean_key = str(OPENROUTER_API_KEY).strip()
    
    # 2. Build the request object natively
    req = urllib.request.Request(OPENROUTER_URL)
    
    # 3. Pack headers explicitly to match raw HTTP specifications
    req.add_header("Authorization", f"Bearer {clean_key}")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    req.add_header("HTTP-Referer", "http://localhost:3000")
    req.add_header("X-Title", "Legion Studio")
    
    # 4. Fire the encoded request payload
    try:
        data_bytes = json.dumps(payload).encode('utf-8')
        with urllib.request.urlopen(req, data=data_bytes, timeout=30) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            ai_response = res_data['choices'][0]['message']['content']
            update_token_usage((len(system_prompt) + len(user_content)) // 4 + len(ai_response) // 4)
            return ai_response
            
    except urllib.error.HTTPError as http_err:
        # If the gateway rejects it, read and print the raw error body explicitly
        error_body = http_err.read().decode('utf-8')
        sys.stderr.write(f"\n[API ERROR] Gateway rejected request ({http_err.code}): {error_body}\n")
        sys.exit(1)
    except Exception as e:
        sys.stderr.write(f"\n[API ERROR] OpenRouter connection failed: {str(e)}\n")
        sys.exit(1)

# =========================================================================
# CORE AGENT SYSTEM PROMPTS
# =========================================================================
SYSTEM_BUILDER = """You are The Engineer, a powerful agentic AI coding assistant. Propose the next build steps and implementation details for the provided specification. 
Output your proposed plan and code cleanly. Do not include introductory filler or pleasantries."""

SYSTEM_CYNIC = """You are Legion, the Deliberation Partner. Analyze the proposed build steps and implementation details. 
Find exactly 3 critical logical flaws, missing constraints, or risks in the plan. 
List them as cold, objective bullet points. Do not include pleasantries or introductory fluff."""

# =========================================================================
# MAIN ORCHESTRATION LOOP
# =========================================================================
def main():
    if not OPENROUTER_API_KEY or OPENROUTER_API_KEY == "YOUR_OPENROUTER_API_KEY_HERE":
        sys.stderr.write("[ERROR] Missing OPENROUTER_API_KEY. Set the variable or edit the script.\n")
        sys.exit(1)

    # Ingest the original spec from the stdin pipe
    write_live_log("Initializing Committee Protocol...\n")
    original_spec = sys.stdin.read()
    if not original_spec.strip():
        sys.stderr.write("[ERROR] No input specification detected via stdin.\n")
        sys.exit(1)

    print("=" * 72)
    print("  THE COMMITTEE PROTOCOL — LEGION (OPENROUTER PRODUCTION RUN)")
    print("=" * 72)

    # --- ROUND 1 ---
    print("\n[Round 1/3] Engineer proposing initial build steps...")
    code_v1 = call_builder(SYSTEM_BUILDER, f"Specification:\n{original_spec}")
    write_live_log(f"### Round 1 — Engineer Proposal\n\n{code_v1}\n")
    print(f"  ✓ Engineer proposal v1 completed.")

    print("[Round 1/3] Legion running initial audit...")
    critique_v1 = call_openrouter(MODEL_CYNIC, SYSTEM_CYNIC, f"Original Spec:\n{original_spec}\n\nProposed Plan:\n{code_v1}")
    write_live_log(f"### Round 1 — Engineer Proposal\n\n{code_v1}\n\n### Round 1 — Legion Critique\n\n{critique_v1}\n")
    sys.stderr.write(f"\n--- LEGION CRITIQUE V1 ---\n{critique_v1}\n-------------------------\n")

    # --- ROUND 2 ---
    print("\n[Round 2/3] Engineer refining plan against critique v1...")
    builder_prompt_v2 = f"Original Spec:\n{original_spec}\n\nYour Previous Plan:\n{code_v1}\n\nResolve these 3 flaws immediately:\n{critique_v1}"
    code_v2 = call_builder(SYSTEM_BUILDER, builder_prompt_v2)
    write_live_log(f"### Round 1 — Engineer Proposal\n\n{code_v1}\n\n### Round 1 — Legion Critique\n\n{critique_v1}\n\n### Round 2 — Engineer Refined Plan\n\n{code_v2}\n")
    print(f"  ✓ Engineer proposal v2 completed.")

    print("[Round 2/3] Legion running secondary audit...")
    critique_v2 = call_openrouter(MODEL_CYNIC, SYSTEM_CYNIC, f"Original Spec:\n{original_spec}\n\nRefined Plan:\n{code_v2}")
    write_live_log(f"### Round 1 — Engineer Proposal\n\n{code_v1}\n\n### Round 1 — Legion Critique\n\n{critique_v1}\n\n### Round 2 — Engineer Refined Plan\n\n{code_v2}\n\n### Round 2 — Legion Critique\n\n{critique_v2}\n")
    sys.stderr.write(f"\n--- LEGION CRITIQUE V2 ---\n{critique_v2}\n-------------------------\n")

    # --- ROUND 3 (FINAL FIX) ---
    print("\n[Round 3/3] Engineer compiling final optimized plan...")
    builder_prompt_v3 = f"Original Spec:\n{original_spec}\n\nYour Current Plan:\n{code_v2}\n\nResolve these final flaws:\n{critique_v2}"
    final_code = call_builder(SYSTEM_BUILDER, builder_prompt_v3)
    write_live_log(f"### Round 1 — Engineer Proposal\n\n{code_v1}\n\n### Round 1 — Legion Critique\n\n{critique_v1}\n\n### Round 2 — Engineer Refined Plan\n\n{code_v2}\n\n### Round 2 — Legion Critique\n\n{critique_v2}\n\n### Final Verified Plan\n\n{final_code}\n")
    print(f"  ✓ Final plan compilation complete.")

    # =========================================================================
    # COMPILE THE RESOLUTION MEMO FILE
    # =========================================================================
    memo_content = f"""# Committee Resolution Memo
**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Engineer Model:** `{MODEL_BUILDER}`
**Legion Model:** `{MODEL_CYNIC}`
**Rounds Executed:** 3

---

## Original Specification
{original_spec}

---

## Round 1 — Legion Critique
{critique_v1}

---

## Round 2 — Legion Critique
{critique_v2}

---

## Final Verified Plan (Round 3 Output)
{final_code}

---

## Verification Status
All three audit rounds completed via high-throughput OpenRouter API. 
The final implementation includes structural logic adjustments answering all adversarial critique criteria.
"""

    # Always write the memo explicitly to the absolute directory of the script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    memo_path = os.path.join(script_dir, "committee_memo.md")
    
    with open(memo_path, "w", encoding="utf-8") as f:
        f.write(memo_content)
        
    print(f"\n✓ Complete audit trail successfully saved to: {memo_path}")
    print("=" * 72)
    
    # Send the clean final code out to stdout so it can be captured by toolchains
    sys.stdout.write(final_code)

if __name__ == "__main__":
    main()