# Contributing to ResolveOps

ResolveOps accepts focused fixes that preserve one rule: models may advise, but deterministic code
owns authorization, approval, execution, and verification.

Before opening a pull request:

1. Create an issue for a behavioral or architectural change. Small bug and documentation fixes can
   go directly to a pull request.
2. Keep changes inside the existing FastAPI, LangGraph, SQLAlchemy, and no-build console stack.
3. Add a regression test for changed behavior. New model behavior also needs a versioned evaluation
   case; never weaken an expectation merely to make a run pass.
4. Use synthetic data only. Never commit credentials, real personal data, provider transcripts, or
   unreviewed model text as trusted memory.
5. Run the checks below and describe any check you could not run.

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check src tests migrations scripts
.\.venv\Scripts\mypy.exe src
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/run_agent_evaluation.py
.\.venv\Scripts\python.exe scripts/run_memory_ablation.py
```

Pull requests should explain the user-visible problem, the control boundary affected, evidence from
tests or evaluation, and any remaining risk. Keep local and live-provider measurements separate;
leave unavailable token or cost fields unknown.

For vulnerability reports, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.
