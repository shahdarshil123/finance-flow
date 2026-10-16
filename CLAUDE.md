
# FinanceFlow AI — Engineering Guidelines

## Project Objective
Build a reliable AI-assisted financial document processing
and accounts payable automation system.

## Development Principles
- Prefer a modular monolith over premature microservices.
- Separate domain logic from APIs, databases, and AI providers.
- Keep financial calculations deterministic using Decimal.
- Treat LLM output as untrusted until validated.
- Make side-effecting operations idempotent.
- Design for retries, concurrent requests, and failures.
- Use synthetic financial data during development.

## Before Implementing
1. Explain the requested change and affected components.
2. Identify at least two potential failure scenarios.
3. Describe any database or API contract changes.
4. Propose a minimal implementation plan.
5. Wait for approval before substantial changes.

## During Implementation
- Make small, reviewable changes.
- Avoid unrelated refactoring.
- Write tests for success, failure, and boundary cases.
- Keep dependencies behind appropriate interfaces.
- Avoid unnecessary abstractions.

## After Implementing
- Summarize the files changed.
- Explain important engineering decisions.
- Show test results and any tests not executed.
- Identify remaining risks and technical debt.
- Suggest one realistic failure scenario to test.
