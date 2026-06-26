---
name: code-review
description: Best practices for reviewing generated Python code for security, performance, and maintainability
triggers: [review, check, audit, inspect]
---

# Code Review Skill

When reviewing generated code, check for:

1. **Security**: SQL injection, hardcoded secrets, missing auth checks
2. **Performance**: N+1 queries, unnecessary loops, missing caching
3. **Type Safety**: Missing type hints, Optional not handled, bare `dict` usage
4. **Error Handling**: Missing try/except, swallowed exceptions, no logging
5. **API Design**: RESTful conventions, proper status codes, input validation

Output format: Always respond with JSON:
{"verdict": "pass|fail|conditional", "issues": [...], "metrics": {...}}
