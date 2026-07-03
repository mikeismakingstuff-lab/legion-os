# Specification: Legion OS — Pipeline Architecture Evaluation (LangGraph vs. Pure Python)

## Objective
Evaluate the architectural trade-offs between two approaches for the Legion OS pipeline execution framework and implement the recommended solution.

### Approach A: LangGraph Framework
- Uses `langgraph.graph.StateGraph` to compile and execute the pipeline.
- Requires external dependencies: `langgraph`, `pydantic`, `anyio`, etc.
- Uses conditional edges for routing (e.g., error handling, shishi-odoshi hold, retraction circuit breaker).

### Approach B: Pure Python StateMachine (Zero-Dependency)
- Uses a custom, lightweight Python class (`LegionStateMachine`) to manage node execution and routing.
- Zero external dependencies (standard library only).
- Uses explicit `if/elif` branching and loops for routing.

---

## Evaluation Criteria & Findings

1. **Component Weight & Profile Impact:**
   - Approach A requires ~120MB of dependencies and adds ~700ms cold-start overhead due to Pydantic schema compilation.
   - Approach B has 0MB footprint and <5ms import time.
   - *Context:* The local hardware is an Intel Iris Xe CPU-only system. Shared VRAM means memory overhead directly competes with local LLM inference weights.

2. **Looping & Timeout Resilience (Shishi-Odoshi):**
   - Approach A requires external orchestration or a state persistence layer (`SqliteSaver`) to handle the pending retry loop gracefully without infinite loops.
   - Approach B can implement a native `while` loop with a sleep interval and loop counter in a few lines of code.

3. **Fault Isolation & Adjudication (Retraction Circuit Breaker):**
   - Approach A handles exceptions at the node boundary, converting them to state flags for conditional routing.
   - Approach B handles exceptions explicitly in the dispatcher loop, providing a clean Python traceback and easier debugging.

4. **Data Re-Read Hygiene (DB-as-Contract):**
   - The pipeline uses a strict "Database-as-Contract" pattern where stages read/write from SQLite by `mission_id`.
   - The State passport only carries tracking strings/booleans, making LangGraph's rich state-merging features redundant.

---

## Committee Task
1. Analyze these findings. Provide a brief, objective critique of both approaches.
2. Implement the final recommended architecture (either a clean `LegionStateMachine` class or the compiled `StateGraph` setup) as a production-grade Python module.
3. If implementing the Pure Python `LegionStateMachine`, ensure it:
   - Accepts a `PipelineState` dict.
   - Wraps each stage node in exception handling.
   - Implements the loop back from `arbitration` to `weigh` with a retry limit (max 3 retries) to prevent infinite loops.
   - Implements the shishi-odoshi pending hold gracefully.
