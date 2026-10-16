---
name: verify-and-fix
description: Verify FinanceFlow AI implementation changes, diagnose failures, apply minimal safe fixes, and rerun tests. Use after completing a scoped code change.
disable-model-invocation: true
---

# FinanceFlow AI — Verify and Fix

## Objective

Verify newly implemented functionality while preserving
existing behavior, architecture, and code quality.

Never optimize only for passing tests.

## Step 1 — Establish the baseline

Before changing anything:

1. Identify the current Git branch.
2. Identify the last verified commit.
3. Inspect git status and the current diff.
4. Determine the business requirement being implemented.
5. Identify files relevant to that requirement.
6. Preserve any user-authored uncommitted changes.

Never run git reset --hard, git clean, or destructive
commands to resolve test failures.

## Step 2 — Run verification

Run these checks when configured:

- uv run ruff check .
- uv run ruff format --check .
- uv run pyright
- uv run pytest -q

For database changes, also run relevant Alembic checks
against a dedicated test database.

Capture exit codes, errors, and warnings.

Do not confuse a missing tool or unavailable PostgreSQL
instance with a successful check.

## Step 3 — Diagnose failures

For each failure:

1. Identify the failing component.
2. Explain the expected behavior.
3. Determine the likely root cause.
4. Identify the smallest safe correction.
5. Check whether the issue predates the current change.

Do not make unrelated changes to hide errors.

## Step 4 — Apply minimal fixes

You may fix clear implementation defects automatically.

Rules:
- Do not delete or weaken existing tests.
- Do not remove database constraints.
- Do not suppress type errors without justification.
- Do not modify business requirements.
- Do not introduce new dependencies unnecessarily.
- Do not change public API contracts without approval.
- Do not refactor unrelated code.
- Do not change financial validation behavior without approval.
- Do not change Alembic migrations already applied
  to shared environments without approval.

If an issue requires an architectural decision, stop
and request human review.

## Step 5 — Re-verify

After each correction:

1. Run the specific regression test.
2. Run the relevant test module.
3. Run the complete verification suite.
4. Examine the new Git diff.
5. Confirm the change did not introduce unrelated edits.

Maximum automatic repair attempts: 2.

If verification still fails, stop and report the
unresolved issue instead of continuing indefinitely.

## Step 6 — Review code quality

Evaluate:
- Separation of concerns
- Duplicate code
- Unnecessary abstractions
- Complexity introduced by the fix
- Transaction correctness
- Error handling
- Extensibility
- New failure scenarios

Passing tests does not automatically mean the design
is acceptable.

## Step 7 — Final report

Produce:

### Verification results
- Commands executed
- Passed, failed, or blocked
- Test counts and warnings

### Changes made
- Files modified
- Root causes corrected
- Regression tests added

### Engineering assessment
- Code quality impact
- Architectural concerns
- Remaining risks
- Known limitations

### Decision
PASS / PASS WITH WARNINGS / FAIL

Do not commit or push changes.
