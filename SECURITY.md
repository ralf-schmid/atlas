# Security Policy

ATLAS is a private, single-operator research project that trades with real
brokerage credentials (paper first, live later). Security issues are treated
with priority over feature work.

## Reporting a vulnerability

Report privately via GitHub's **"Report a vulnerability"** button
(Security → Advisories) on this repository. Do **not** open a public issue for
anything that could expose credentials, order-placement paths, or the
paper/live separation.

Please include: affected component (`src/...`), reproduction steps, and impact.

## Automated detection in place

- **Dependabot** — version + security updates for `uv` (Python), `npm` (web)
  and `github-actions`. Dev-dependency patch updates auto-merge on green CI.
- **pip-audit** / **npm audit** — dependency CVE reporting in CI (report-only).
- **bandit** — static application-security scan of `src/` in CI (report-only).
- **gitleaks** — secret scanning in pre-commit and CI (blocking).

## Non-negotiable invariants

Security invariants (deterministic risk gate, privilege separation,
paper/live separation, secrets never in the repo, cost caps, circuit breaker)
are defined in `CLAUDE.md` and `ARCHITECTURE.md` and must not be weakened to
land a fix.
