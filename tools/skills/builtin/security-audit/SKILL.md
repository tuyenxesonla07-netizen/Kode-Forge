---
name: security-audit
description: Security audit patterns for generated code — injection prevention, auth, secrets
triggers: [security, auth, jwt, injection, vulnerability, xss, csrf]
---

# Security Audit Skill

When auditing generated code for security:

## OWASP Top 10 Checks

1. **Injection**: No string interpolation in SQL/commands — use parameterized queries
2. **Auth**: JWT tokens validated, expiration checked, refresh tokens rotated
3. **Secrets**: No hardcoded API keys, passwords, or tokens — use environment variables
4. **CORS**: Properly configured with allowed origins whitelist
5. **Input Validation**: All inputs validated with Pydantic schemas
6. **Rate Limiting**: Endpoints protected against brute force
7. **HTTPS**: No hardcoded HTTP URLs in production code

## Dangerous Patterns to Flag

```python
# DANGEROUS — flag these:
eval(user_input)
exec(user_input)
os.system(f"cmd {user_input}")
subprocess.call(user_input, shell=True)
f"SELECT * FROM users WHERE id = {user_id}"  # SQL injection
```

## Safe Alternatives

```python
# SAFE — encourage these:
ast.literal_eval(validated_input)
subprocess.run(["cmd", arg1, arg2], shell=False)
text("SELECT * FROM users WHERE id = :id").bindparams(id=user_id)
```
