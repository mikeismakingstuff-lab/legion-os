---
description: Adversarial Committee Gatekeeper — mandatory pre-write review via OpenRouter LLMs for Python scripts, shell scripts, and DB schemas
---

# Committee Gatekeeper Workflow

This workflow MUST be executed before any `+` (new file creation) or major
refactor of a Python script, shell script, or database schema. No exceptions.

---

## Steps

1. **Compile a standalone specification block** for the proposed implementation.
   Write it to a temporary file at `E:\Legion\_committee_spec.md`.
   The spec must include:
   - Objective (one paragraph)
   - Requirements (numbered list)
   - Hard Constraints (numbered list)
   Do NOT include any proposed code — the committee generates the code.

// turbo
2. **Pipe the spec through the committee** from the Legion workspace root:
   ```
   Get-Content E:\Legion\_committee_spec.md | python E:\Legion\committee.py
   ```
   Wait for the process to exit. The committee runs 3 rounds and writes its
   output to `E:\Legion\committee_memo.md`.

3. **Read `E:\Legion\committee_memo.md`** in full.

4. **Parse the audit history:**
   - Read all Cynic critique rounds.
   - Identify load-bearing fixes: exception handling gaps, shared-state bugs,
     security risks, missing edge-case guards, type-safety issues.
   - Discard hallucinated constraints (e.g., CWD lock-in checks, banning MD5
     without a cryptographic justification, imaginary API restrictions).
   - A constraint is hallucinated if it is not traceable to the original spec
     or a real security/correctness concern.

5. **Write the final polished asset** to its target path, incorporating:
   - The committee's final Round 3 code as the structural base.
   - All load-bearing Cynic fixes applied and validated.
   - All hallucinated constraints removed.
   - Production polish: streaming reads for large files, unique key strategies,
     proper relative path handling, CLI entry-point if applicable.
