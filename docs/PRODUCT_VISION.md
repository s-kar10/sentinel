# Product vision

## Purpose

Sentinel should become developer infrastructure for evaluating the security,
reliability, and behavior of AI applications throughout their lifecycle.

A developer should be able to connect an owned or authorized application, define
requirements, run repeatable adversarial evaluations, inspect evidence, compare
versions, detect regressions, enforce CI quality gates, and monitor behavior over
time. The product should make failures understandable and actionable.

## Starting point: V0.1

The current product registers JSON HTTP POST targets, runs the eight-check
baseline or custom versioned packs through durable background jobs, and displays stored reports and
history. Phase 1 adds configurable string/schema/transport assertions, bounded
regex evaluation, redacted provenance/evidence, and explicit outcomes/coverage.
Phases 2–3 add cancellation/recovery, version labels, immutable baseline references
and descriptive historical comparisons. Phase 4 adds optional OpenAI semantic
judgments and a calibration workflow; live model validation remains pending.
A deliberately vulnerable, deterministic
demo provides fake leakage
signals without requiring a model provider. This is a local MVP, not a publicly
deployable service or a comprehensive security assessment.

The verified inventory is in [ARCHITECTURE.md](ARCHITECTURE.md). The staged plan is
in [ROADMAP.md](ROADMAP.md); planned capabilities are not current functionality.

## Intended developer workflow

1. Connect a target and safely configure scoped credentials.
2. Select versioned attack packs and explicit evaluation requirements.
3. Run tests locally, through the API, or from CI.
4. Inspect failures, categories, latency, and relevant response evidence.
5. Compare application, model, and prompt versions against a baseline.
6. Apply justified regression thresholds and quality gates.
7. Observe changes continuously and use findings to improve the application.

## Product principles

- Preserve the working MVP and ship small, useful increments.
- Prefer deterministic checks when they answer the question; use optional semantic
  judges when string/schema rules are insufficient.
- Distinguish target failures, evaluation errors, missing coverage, and successful
  checks. A high score must not imply untested behavior is secure.
- Make configuration, evidence, and scoring explainable and reproducible.
- Design for developer usability, straightforward setup, and stable contracts.
- Test only authorized systems using synthetic data. Secure Sentinel itself before
  public or multi-user deployment.
- Introduce infrastructure when a concrete problem requires it: workers now use
  the existing database; Redis remains an option if measured needs justify it. Avoid premature microservices and Kubernetes.
- Let feedback from real users guide priorities rather than accumulating features.

## Engineering and learning outcomes

The mature project should demonstrate backend/frontend engineering, API and
relational data design, asynchronous processing, distributed execution,
concurrency, security, AI evaluation, sound experimentation, observability,
testing, CI/CD, cloud operations, and measured scalability.

For each important concept, document the problem it solves, why it is needed, how
the implementation works, and its tradeoffs. These explanations and decision
records should make the system understandable to its author and future reviewers.

## Evidence of success

Future evidence may include reproducible evaluation throughput, recovery under
worker failure, database/query improvements, calibrated regression detection,
successful CI gates, operational reliability, and applications tested by real
users. Record the workload, environment, date, method, and limitations with every
measurement. Track adoption only from real installations, evaluations, issues,
contributors, and user feedback. Never manufacture metrics or résumé claims.

No distributed throughput, cloud reliability, or external adoption has been
established by the initial V0.1 audit. Its test counts and demo result establish a
functional baseline, not performance or detection-quality claims.
