# Specification: Evolving Legion OS Graph Topography

## Objective
Analyze the current `legion_graph.py` layout and design a strategy to integrate Stage 1 (Ingest) and Stage 2 (Parse) directly into the StateGraph topology.

## Requirements
1. **Dynamic Stage 1 Loop:** Rather than handling Ingest externally, integrate it as a Graph Node. Use the `batch_promoted` flag from `PipelineState` along with a conditional edge to create a looping gate. If the Shishi-Odoshi threshold isn't met, loop back or transition to a 'PENDING_RETRY' status instead of crashing out.
2. **Circuit Breaker Integration:** Identify the exact placement between Stage 4 (Weigh) and Stage 5 (Deliberate) to mount the `retraction_engine.py` logic. Ensure that if a blast radius calculation flags a high-exposure risk (>15%), the graph routes dynamically to a dedicated arbitration node rather than throwing an unhandled exception.
3. **Strict State Continuity:** Maintain zero external library dependencies. The state passport must remain a lightweight tracker passing only UUID strings and database keys.

