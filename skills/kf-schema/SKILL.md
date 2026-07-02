---
name: kf-schema
description: Scaffold a new KodeForge module by generating the required input/output JSON Schema pair. Usage: /kf-schema <module-name>
triggers: [kf-schema, kodeforge schema, forge schema]
version: 1.0.0
---

# KodeForge Schema Scaffolder — /kf-schema

Generate a new module's JSON Schema pair (`<name>_input.json` + `<name>_output.json`) and register it in `config/agents.yaml`.

## How to use

When the user invokes `/kf-schema <module-name>`:

1. **Parse the module name** from the argument (e.g., `payment`, `notification`, `search`).

2. **Create `config/schemas/<name>_input.json`** with this structure:
   ```json
   {
     "$schema": "http://json-schema.org/draft-07/schema#",
     "title": "<Title> Module Input",
     "type": "object",
     "required": ["requirement", "constraints", "dependencies"],
     "properties": {
       "requirement":  { "type": "string",  "description": "Module requirement description" },
       "constraints":  { "type": "array",   "items": { "type": "string" }, "description": "Technical constraints" },
       "dependencies": { "type": "array",   "items": { "type": "string" }, "description": "External module dependencies" },
       "tech_stack":   {
         "type": "object",
         "properties": {
           "language":  { "type": "string" },
           "framework": { "type": "string" },
           "database":  { "type": "string" }
         }
       }
     }
   }
   ```

3. **Create `config/schemas/<name>_output.json`** with the standard output contract:
   ```json
   {
     "$schema": "http://json-schema.org/draft-07/schema#",
     "title": "<Title> Module Output",
     "type": "object",
     "required": ["module_spec", "confidence", "reasoning"],
     "properties": {
       "module_spec": {
         "type": "object",
         "required": ["components", "interfaces", "acceptance_criteria"],
         "properties": {
           "components":           { "type": "array", "items": { "type": "object" } },
           "interfaces":           { "type": "array", "items": { "type": "object" } },
           "acceptance_criteria":  { "type": "array", "items": { "type": "string" } }
         }
       },
       "confidence": { "type": "number", "minimum": 0, "maximum": 1 },
       "reasoning":  { "type": "string" }
     }
   }
   ```

4. **Append to `config/agents.yaml`** under the `experts:` key:
   ```yaml
   expert_<name>:
     capabilities: [<name>_design, <name>_implementation]
     dependencies: []
   ```

5. **Confirm** by listing the files created and reminding the user:
   > No Python code needed. Run `/kf-run` to use the new module immediately.

## Example

User: `/kf-schema payment`

Creates:
- `config/schemas/payment_input.json`
- `config/schemas/payment_output.json`
- Appends `expert_payment` entry to `config/agents.yaml`
