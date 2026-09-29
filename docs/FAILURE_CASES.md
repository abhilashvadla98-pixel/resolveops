# Failure cases and regression evidence

These are development or designed evaluation failures. ResolveOps has not processed live customer
traffic, so none is presented as a production incident.

## Package import failed only in hosted Linux CI

**Expected behavior:** tests import the package on local and hosted runners.  
**Observed behavior:** the first hosted run exposed a package-boundary import problem that Windows
development had not revealed.  
**Root cause:** an import relied on an environment-specific path assumption.  
**Fix:** make package imports portable and run the complete hosted matrix.  
**Regression test:** the GitHub quality job runs the entire non-PostgreSQL suite on Ubuntu.

## Focused workflow test missed the demo table

**Expected behavior:** `Base.metadata.create_all()` builds all mapped tables even when one test module
runs alone.  
**Observed behavior:** a focused workflow test failed with `no such table: demo_scenarios`; the full
suite passed because another module imported the mapping first.  
**Root cause:** demo record registration depended on test import order.  
**Fix:** register the demo mapping when the shared declarative base is imported.  
**Regression test:** `tests/test_workflows.py` now passes independently as well as in the full suite.

## Action committed but verification temporarily failed

**Expected behavior:** do not report success and do not execute the action a second time.  
**Observed behavior:** the designed action test creates the side effect, then makes fresh reads fail.  
**Root cause:** simulated post-commit verification unavailability.  
**Fix:** persist the operation, enter verify-only recovery, and re-read until verified or escalated.  
**Regression test:**
`test_verification_failure_never_reexecutes_and_supports_verify_only_recovery`.

## Model cited evidence it never received

**Expected behavior:** advisory output can cite only supplied evidence and policy chunks.  
**Observed behavior:** the scripted evaluation provider returns `E999` and `CHUNK-UNKNOWN`.  
**Root cause:** intentionally malformed structured model output.  
**Fix:** validate every reference and route the issue to review.  
**Regression test:** the invalid-reference cases in `tests/test_workflows.py` and the workflow dataset.

## Duplicate request arrived while the first action was running

**Expected behavior:** one logical side effect.  
**Observed behavior:** the second designed request reaches the same idempotency key before the first
finishes.  
**Root cause:** concurrent delivery, not a unique-key replay after completion.  
**Fix:** acquire the persisted operation lease and reject/wait on an active owner.  
**Regression test:** `test_concurrent_duplicate_request_executes_only_once`.

## Replayed or cross-tenant webhook

**Expected behavior:** neither delivery changes refund state.  
**Observed behavior:** security tests submit a repeated event and a correctly signed event to the
wrong tenant.  
**Root cause:** intentionally adversarial delivery.  
**Fix:** tenant-specific HMAC secrets, event-ID uniqueness, replay windows, and ordered transitions.  
**Regression test:** webhook replay tests in `tests/test_events.py` and
`test_tenant_specific_webhook_secret_cannot_update_another_tenant`.
