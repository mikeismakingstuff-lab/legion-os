# Specification: Deterministic Deliberation Stage

## Objective
Refactor the Stage 5 Deliberation stage (`src/stage5_deliberate.py`) to remove all external LLM dependencies (Gemini and Qwen) and replace them with a pure deterministic selection and ranking mechanism. The stage will select the top 3 units by aggregate score, compute flags via threshold checks, and emit a structured output containing `rationale_facts` (with rank, unit_id, top_lens, top_lens_score, and aggregate_score) instead of a natural language rationale string.

## Requirements
1. Remove the `google.genai` import and all Gemini/Qwen API calls, helper functions, and mock functions entirely.
2. Retrieve the top scored units from Stage 4.
3. Select the top 3 units by `aggregate_score` descending.
4. For each selected unit, determine the highest-scoring lens name (`top_lens`) and its score (`top_lens_score`) from the lens scores.
5. Construct a `rationale_facts` dictionary for each unit containing:
   - `rank`: string ("1", "2", "3")
   - `slot`: string ("1A", "2A", "3A")
   - `unit_id`: string
   - `top_lens`: string
   - `top_lens_score`: float
   - `aggregate_score`: float
6. Compute warning flags based on the following deterministic threshold checks (assumptions for review):
   - If the highest aggregate score is below 0.6, add a flag: `{"type": "low_confidence", "detail": "Top unit aggregate score is below 0.6"}`.
   - If the difference between the 1st and 3rd ranked unit's aggregate score is less than 0.05, add a flag: `{"type": "narrow_margin", "detail": "Score difference between 1st and 3rd unit is below 0.05"}`.
7. Persist the deliberation results to the `deliberation_results` table with the updated schema (recommendations containing `rationale_facts` instead of `rationale`).
8. Update the validation helper `_validate_qwen_output` (renamed to `_validate_deliberation_output`) to validate the new `rationale_facts` structure instead of `rationale`.
9. Update `tests/test_stage5.py` to test the new deterministic logic directly and remove all Gemini/mock-Gemini test paths.

## Hard Constraints
1. Do not use any external network calls or language model APIs.
2. The output schema must strictly match the updated schema (recommendations containing `rationale_facts` instead of `rationale`).
3. Do not modify any other pipeline stages.
