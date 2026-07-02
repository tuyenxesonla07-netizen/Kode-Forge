---
name: kf-run
description: Run the KodeForge Schema-First pipeline on a natural language requirement. Usage: /kf-run <requirement>
triggers: [kf-run, kodeforge run, forge run]
version: 1.0.0
---

# KodeForge Pipeline — /kf-run

Run the full Schema-First multi-agent code generation pipeline.

## How to use

When the user invokes `/kf-run <requirement>`, execute the following steps:

1. **Validate** that a requirement was provided. If not, ask the user for one.

2. **Check for API key** — look for `ANTHROPIC_API_KEY` in the environment:
   - If present: use `llm_backend="anthropic"`
   - If absent: use `llm_backend="mock"` and inform the user

3. **Run the pipeline** by executing in the terminal from the project root:
   ```bash
   python -c "
   from agents.pipeline import generate_code
   import json, sys
   result = generate_code(
       requirement='''$REQUIREMENT''',
       config_dir='config',
       llm_backend='$LLM_BACKEND',
       enable_guardrails=True,
   )
   print(json.dumps(result, indent=2, default=str))
   "
   ```

4. **Report results** clearly:
   - If `status == "success"`: show the generated modules, line counts, quality score, and any written files
   - If `status == "blocked"`: show the guardrail reason and suggest rephrasing
   - If `status == "awaiting_approval"`: explain that HITL approval is required

5. **Show the event trail** if `tools/workflow/event_store.py` is available:
   ```bash
   python -c "from tools.workflow.event_store import PipelineEventStore; [print(e.event_type, e.data) for s in PipelineEventStore.list_runs() for e in PipelineEventStore.load(s).events]"
   ```

## Example

User: `/kf-run Build a JWT authentication module with FastAPI`

Expected output:
- Pipeline status
- Modules generated (e.g., authentication, api_integration)
- Code preview for the first module
- Quality score
- Files written to `src/`
