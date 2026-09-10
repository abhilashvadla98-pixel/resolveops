# ResolveOps Engineering Rules

## 1. Project Goal

ResolveOps is a production-grade AI engineering portfolio project.

It must demonstrate:
- real backend engineering
- RAG
- agent orchestration
- multi-agent workflows
- tool/function calling
- MCP
- durable state
- human-in-the-loop
- reliability
- security
- evaluation
- observability
- Docker
- CI/CD
- cloud deployment

Do not reduce ResolveOps into a chatbot or simple demo.

## 2. Architecture Rule

Do not redesign the architecture without explicit approval.

Use deterministic code for:
- permissions
- RBAC
- approval rules
- idempotency
- state validation
- financial/action limits
- authentication
- authorization

Use LLMs only where reasoning adds value.

## 3. Coding Rule

Use:
- Python 3.12
- type hints
- Pydantic models
- clear function names
- small modules
- explicit error handling

Avoid:
- giant files
- hidden magic
- unexplained shortcuts
- hardcoded secrets

## 4. Security Rule

Never commit:
- API keys
- passwords
- tokens
- secrets
- .env files

Use environment variables for secrets.

## 5. Testing Rule

Every meaningful feature must have tests.

Before a task is complete:
- code must run
- tests must pass
- expected behavior must be verified
- failures must be understood

## 6. Debugging Rule

When something fails:
1. identify symptom
2. inspect logs/output
3. form hypothesis
4. reproduce
5. find root cause
6. fix
7. add regression test where useful

Do not replace large parts of the system without diagnosing the cause.

## 7. AI Agent Rule

Do not create agents just to increase agent count.

Each agent must have a justified responsibility.

Prefer deterministic nodes when an LLM adds no value.

## 8. Data and Database Rule

Use proper schemas and migrations.

Do not manually change production-style database structure without migrations.

Synthetic data must be realistic and structured.

## 9. Metrics Rule

Never invent:
- accuracy
- latency
- cost
- task success
- retrieval improvement
- throughput
- business savings

Only report measured results.

## 10. Definition of Done

A task is complete only when:
- implementation is finished
- tests pass
- acceptance criteria pass
- important behavior is manually verified
- documentation is updated where required
- the repository remains working