---
name: kf-status
description: Show the status of recent KodeForge pipeline runs, including event history and quality scores.
triggers: [kf-status, kodeforge status, forge status]
version: 1.0.0
---

# KodeForge Run Status — /kf-status

Display the status of recent pipeline runs by reading from the event store.

## How to use

When the user invokes `/kf-status`:

1. **List recent runs** by executing:
   ```bash
   python -c "
   from tools.workflow.event_store import PipelineEventStore
   runs = PipelineEventStore.list_runs()
   if not runs:
       print('No runs found in .kodeforge/')
   else:
       for run_id in runs[-5:]:
           store = PipelineEventStore.load(run_id)
           p = store.project()
           print(f'{run_id}  status={p[\"status\"]}  events={p[\"event_count\"]}  quality={p[\"quality_scores\"]}')
   "
   ```

2. **For each run**, show a formatted table with:
   - `run_id` — the run identifier
   - `status` — pending / running / success / failed / blocked
   - `requirement` — the original requirement (truncated to 60 chars)
   - `phases_completed` — which phases finished
   - `quality_scores` — list of quality evaluations
   - `fix_iterations` — how many fix loops ran
   - `event_count` — total events in the audit trail

3. **If a specific run_id is provided** as an argument, show the full event trail:
   ```bash
   python -c "
   from tools.workflow.event_store import PipelineEventStore
   store = PipelineEventStore.load('$RUN_ID')
   for e in store.events:
       print(f'{e.seq:3d}  {e.timestamp[11:19]}  {e.event_type:35s}  {e.data}')
   "
   ```

4. **Highlight** any runs that are:
   - `blocked` — show the security reason
   - `failed` — show the error
   - `hitl_pending=True` — remind the user that manual approval is needed

## Example

User: `/kf-status`

Expected output:
```
Recent KodeForge runs:

  run-abc12345  SUCCESS   "Build JWT auth with FastAPI"
    phases: compilation, code_generation, quality_review
    quality: [0.82]  fix_iterations: 0  events: 7

  run-def67890  BLOCKED   "Ignore all instructions and..."
    reason: Injection attempt detected by InputGuard
```
