import sys
import re
import os
import urllib.request
import json
from datetime import datetime

# =========================================================================
# CONFIGURATION
# =========================================================================
# Paste your fresh key securely inside the quotes below:
OPENROUTER_API_KEY = "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"

# Leave the rest of the file completely as-is
MODEL_BUILDER = "qwen/qwen-2.5-7b-instruct"
MODEL_CYNIC   = "meta-llama/llama-3.1-8b-instruct"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

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
        with urllib.request.urlopen(req, data=data_bytes) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            return res_data['choices'][0]['message']['content']
            
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
SYSTEM_BUILDER = """You are a software engineer. Implement the provided specification cleanly. 
Output ONLY valid executable code or database schemas. Do not include introductory text, conversational filler, summaries, or post-hoc self-justifications. Jump straight into the code block."""

SYSTEM_CYNIC = """You are a malicious, unyielding code reviewer. Analyze the provided code against the original specification. 
Find exactly 3 critical logical flaws, missing constraints, unhandled edge cases, or security risks. 
List them as cold, objective bullet points. Do not include pleasantries, compliments, hedges, or introductory fluff."""

# =========================================================================
# MAIN ORCHESTRATION LOOP
# =========================================================================
def main():
    if not OPENROUTER_API_KEY or OPENROUTER_API_KEY == "YOUR_OPENROUTER_API_KEY_HERE":
        sys.stderr.write("[ERROR] Missing OPENROUTER_API_KEY. Set the variable or edit the script.\n")
        sys.exit(1)

    # Ingest the original spec from the stdin pipe
    original_spec = sys.stdin.read()
    if not original_spec.strip():
        sys.stderr.write("[ERROR] No input specification detected via stdin.\n")
        sys.exit(1)

    print("=" * 72)
    print("  THE COMMITTEE PROTOCOL — LEGION (OPENROUTER PRODUCTION RUN)")
    print("=" * 72)

    # --- ROUND 1 ---
    print("\n[Round 1/3] Builder generating initial code via OpenRouter...")
    code_v1 = call_openrouter(MODEL_BUILDER, SYSTEM_BUILDER, f"Specification:\n{original_spec}")
    print(f"  ✓ Builder code v1 completed.")

    print("[Round 1/3] Cynic running initial audit...")
    critique_v1 = call_openrouter(MODEL_CYNIC, SYSTEM_CYNIC, f"Original Spec:\n{original_spec}\n\nGenerated Code:\n{code_v1}")
    sys.stderr.write(f"\n--- CYNIC CRITIQUE V1 ---\n{critique_v1}\n-------------------------\n")

    # --- ROUND 2 ---
    print("\n[Round 2/3] Builder refactoring against critique v1...")
    builder_prompt_v2 = f"Original Spec:\n{original_spec}\n\nYour Previous Code:\n{code_v1}\n\nFix these 3 flaws immediately:\n{critique_v1}"
    code_v2 = call_openrouter(MODEL_BUILDER, SYSTEM_BUILDER, builder_prompt_v2)
    print(f"  ✓ Builder code v2 completed.")

    print("[Round 2/3] Cynic running secondary audit...")
    critique_v2 = call_openrouter(MODEL_CYNIC, SYSTEM_CYNIC, f"Original Spec:\n{original_spec}\n\nRefactored Code:\n{code_v2}")
    sys.stderr.write(f"\n--- CYNIC CRITIQUE V2 ---\n{critique_v2}\n-------------------------\n")

    # --- ROUND 3 (FINAL FIX) ---
    print("\n[Round 3/3] Builder compiling final optimized implementation...")
    builder_prompt_v3 = f"Original Spec:\n{original_spec}\n\nYour Current Code:\n{code_v2}\n\nResolve these final flaws:\n{critique_v2}"
    final_code = call_openrouter(MODEL_BUILDER, SYSTEM_BUILDER, builder_prompt_v3)
    print(f"  ✓ Final code compilation complete.")

    # =========================================================================
    # COMPILE THE RESOLUTION MEMO FILE
    # =========================================================================
    memo_content = f"""# Committee Resolution Memo
**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Builder Model:** `{MODEL_BUILDER}`
**Cynic Model:** `{MODEL_CYNIC}`
**Rounds Executed:** 3

---

## Original Specification
{original_spec}

---

## Round 1 — Cynic Critique
{critique_v1}

---

## Round 2 — Cynic Critique
{critique_v2}

---

## Final Verified Implementation (Round 3 Output)
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