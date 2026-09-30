# Security policy

Please do not open a public issue for a suspected vulnerability, exposed credential, or tenant-data
problem. Use GitHub's private vulnerability reporting for this repository instead. Include the
affected revision, a minimal reproduction, impact, and any relevant request or trace identifiers;
remove secrets and personal data from the report.

The supported release is `v1.x` on `main`. Security fixes are made on `main` and included in the
next tagged patch release. No response-time guarantee is offered for this independently maintained
project.

ResolveOps uses synthetic data in its public demo. Do not submit real customer, employee, payment,
identity, or repository data. A provider credential previously appeared outside approved local
secret storage and must be rotated before provider-backed agents are enabled.

The implemented trust boundaries, threat cases, and verified controls are documented in
[docs/SECURITY.md](docs/SECURITY.md) and [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md).
