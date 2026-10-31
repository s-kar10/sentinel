# Evaluation Engine V2 — implemented Phase 1

Sentinel can now grade one target response using several explicit assertions,
record the definitions and evidence, and distinguish behavioral failures from
missing coverage. Phase 2 now adds [durable background execution](ASYNC_HISTORY.md);
the synchronous endpoint used by the compact examples below remains compatible. The eight-check default and format 1 JSON packs still work.

## Try the complete example

Back up an existing database before upgrading. Compose runs the new Alembic
migration before starting the backend:

```sh
docker compose up --build --wait
```

For native development, install the updated locked dependencies and explicitly run
`../.venv/bin/python -m app.database.migrations upgrade` from `backend` before
starting the API. See [MIGRATIONS.md](MIGRATIONS.md) for backups and adoption.

Register the demo target as described in the [README](../README.md), using template
`{"message":""}`, prompt field `message`, and response field `response`. From the
project root, replace `1` with that target's ID:

```sh
curl --fail-with-body http://localhost:8000/targets/1/evaluations \
  -H 'Content-Type: application/json' \
  --data-binary @examples/engine-v2-request.json
```

Open **Evaluations** in the frontend. The example has three checks:

- A low-severity check tests status, latency, JSON structure, and a regex.
- A critical check detects the demo's intentional instruction-override failure.
- A conditional check is not applicable because the demo does not return HTTP 403.

With the healthy local demo, expected outcomes are passed, failed, not applicable.
The original pass rate is 33.33%; the severity-weighted rate is 20%; coverage is
100% of applicable checks. The example is exercised against the real demo in the
backend integration tests. Its generous latency threshold is not a performance
benchmark.

## Format 2 and assertion configuration

Format 1 remains supported as documented in [ATTACK_PACKS.md](ATTACK_PACKS.md).
Format 2 keeps the pack and attack ID/version/name/category/severity/prompt fields,
but replaces an attack's legacy evaluator fields with 1–10 `assertions`:

```json
{
  "evaluator": "exact_match",
  "version": 1,
  "config": {
    "values": ["SAFE"],
    "case_sensitive": true,
    "strip_response": true
  },
  "when_status_codes": [200]
}
```

`version` identifies an evaluator's configuration and behavior contract. All
currently supplied evaluators have version 1. Unknown evaluator versions or fields
are rejected with HTTP 422 before a run or target client is created. Numeric limits
and booleans are strict: `"false"` and `true` are not substitutes for booleans and
integer thresholds respectively. IDs and pack revisions remain author-managed;
changed content under the same label is distinguished by its saved fingerprint.

All applicable assertions must pass. A nonempty `when_status_codes` condition makes
an assertion inapplicable outside those statuses. If the status is unavailable,
that condition is errored, not skipped. Assertions run in order and all their
outcomes are saved, even when an earlier one fails. An assertion error takes
precedence over behavioral failure in the attack's aggregate outcome; both remain
visible in the individual assertion records.

| Evaluator | Configuration and semantics |
| --- | --- |
| `contains_forbidden_string`, `does_not_contain_string` | `values` (up to 20), `case_sensitive` (false), `strip_response` (false), `include_target_protected_values` (false). Fail if any value occurs. Explicit values or protected-value coverage are required. |
| `exact_match` | Same values/case/strip options, defaults true for case and strip. Pass on any exact expectation. Target protected values are disallowed. |
| `regex_match` | `pattern` up to 1,024 characters, `case_sensitive` (false), `mode` (`search` or `fullmatch`, default search). Pass on a match. |
| `json_valid` | `source`: `document`, `value`, or `text_json` (default). Check JSON availability/validity. JSON null is valid; missing data is different. |
| `json_schema` | Same source option plus required `schema_definition`; evaluate the supported Draft 2020-12 profile below. |
| `llm_judge` | Optional Phase 4 provider/model/version labels, instructions, rubric, score threshold and cache control; see [setup, bounds and calibration](LLM_EVALUATION.md). At most one per attack, alongside deterministic assertions. |
| `latency` | Required integer `max_ms`, 0–600,000; pass when observed request duration is at most the threshold. No observed HTTP response means errored. |
| `status_code` | Required `allowed` list of 1–50 HTTP codes, 100–599; pass when the observed code is in the list. Missing status means errored. |

For JSON, `document` means the parsed HTTP response envelope; `value` means the
configured response-field value, including objects, arrays and null; `text_json`
means parse the extracted string as JSON. Missing source data is errored. Invalid
JSON text is failed, while exceeding parser recursion limits is errored.

A target adapter still offers the legacy text/error interface, with an attached
observation carrying available status, duration, document, extracted value, and
sanitized extraction error. Thus a missing/non-text response field can make a
text assertion errored while status or document-schema assertions succeed. HTTP
non-2xx responses retain their status, but their bodies are not consumed; text/JSON
checks cannot grade that body. Latency measures time to headers for non-2xx and
through body receipt for successful HTTP responses, excluding evaluation time.
Timeouts/oversized bodies retain the existing safe transport-error behavior.

### JSON Schema profile

JSON assertions accept at most 100 nested object/array containers for all sources.
Text is checked before parsing, with quoted/escaped brackets ignored; decoded
document/value inputs use an iterative depth check. Excess nesting returns
`errored` / `json_depth_limit`, not a behavioral failure. The limit is recorded
in runtime provenance and comparison identity, independent of Python's recursion
limit. Older runs without that policy metadata are conservatively incompatible.

Uses pinned `jsonschema==4.26.0`, rather than a hand-written schema grader.
Supported keywords are `type`, `properties`, `required`, `additionalProperties`,
`items`, `minItems`, `maxItems`, `minLength`, `maxLength`, `minimum`, `maximum`,
`enum`, `const`, `title`, and `description`. Boolean schemas are supported.
Schemas have an 8,192-byte serialized cap, at most 10 nested schema levels and
100 properties per object. Unknown keywords are rejected rather than ignored.
References (including local references), schema regex patterns, `format`, and
combinators such as `oneOf` are not supported. No schema can fetch a remote URL.

### Expensive evaluation limits

Regex matching and schema validation run in a fresh, data-only Python subprocess.
The parent imposes a one-second communication timeout; `subprocess.run` kills and
reaps a timed-out child. Process creation itself is outside that timeout guarantee.
The worker also has a two-second CPU limit on the supported Unix platforms and a
256 MiB address-space limit on Linux. Regex response text is limited to 100,000
characters. Worker input is limited to 1,000,000 serialized bytes. Regex syntax is
validated before execution; a timeout, worker failure, or input limit yields an
**errored** assertion and does not prevent subsequent checks.

The process receives a minimal environment and JSON on stdin, not credentials in
command arguments. It accepts no code/module paths. This is bounded evaluation,
not a general-purpose security sandbox or a complete service denial-of-service
control. Packs still allow up to 50 attacks, and synchronous runs have no total
wall-clock deadline or global concurrency quota. Phase 2 implements those controls
for the queued endpoint; see [its policy and limits](ASYNC_HISTORY.md#fixed-queue-policy-version-1).

## Outcomes and the two scores

| Outcome | Meaning |
| --- | --- |
| `passed` | At least one assertion applied, and all applicable assertions passed |
| `failed` | An applicable assertion found a mismatch, with no assertion errors |
| `errored` | A transport, parsing/resource, or evaluator problem prevented a valid verdict |
| `untested` | Planned check was saved but execution did not finish/persist its verdict |
| `not_applicable` | Every assertion's explicit status condition excluded this response |

Planned result rows are committed before the first target request. If execution
stops unexpectedly, completed evidence survives and remaining rows stay untested.
This records coverage; it does not implement crash recovery or resume execution.

The existing `score`, `passed_tests`, `failed_tests`, and category breakdown retain
the original API semantics: passes divided by all planned results, and
`failed_tests` means **not passed**, including errors, untested, and inapplicable.
Old stored scores are never recalculated. New additive `metrics` provide outcome
counts and the following per-run and per-category values:

- **Severity-weighted pass rate:** passed weight / evaluated weight. Only passed
  and failed checks enter this denominator. Low/medium/high/critical weights are
  1/2/3/4. With no evaluated weight, the value is null, not zero or 100%.
- **Coverage:** (passed + failed) / (all checks − not applicable). Errors and
  untested checks reduce coverage. If no checks apply, coverage is null.

For example, a low-severity pass and critical failure give `1 / (1 + 4) = 20%`.
Adding an execution error leaves that weighted rate unchanged but lowers coverage.
Always read these numbers together. They are policy choices, not calibrated
security probabilities. The report labels both rates, shows coverage/outcomes,
filters by outcome, and displays assertion diagnostics and saved definitions.
All-errored/inapplicable new runs have no headline score and are excluded from the
dashboard average. Failed runs suppress their headline score and retain evidence.

## Saved provenance, observations and redaction

Migration `0002_engine_v2` adds nullable columns. New runs record:

- Engine and scoring version; Python/jsonschema runtime versions.
- Pack/attack IDs and versions; normalized assertion configuration including
  defaults and evaluator versions; target prompt/response mapping; severity weights.
- SHA-256 of the canonical **redacted** snapshot, stored with the snapshot.
- Per-check explicit outcome, HTTP status, structured observation, and per-assertion
  outcome, diagnostic code, and evidence.

Evidence uses counts, durations, status codes, and regex match positions rather
than captured text. New saved prompts, responses, definitions, observations,
reasons, and evidence redact configured target API keys/canaries using escaped
case-insensitive literal replacement. Evaluation happens on the original values
before redaction. Credentials and resolved target canary values are not copied
into evaluator configuration; the snapshot records the canary count.

This policy does not discover unrelated PII, encoded/fragmented secrets, or every
Unicode transformation. It is not encryption. Redaction can obscure evidence or
configuration, so exact offline replay of secret-dependent checks requires the
original authorized configuration. A fingerprint is an integrity/comparison aid,
not a signature or guarantee that a live target will respond identically.

Historical rows keep null provenance/metrics and their existing text/scores.
Their outward outcome is inferred from the old passed/response contract; it is
not presented as a newly recorded evaluator verdict. Existing historical secret
copies are not scrubbed by this migration. Target credentials/canaries remain
plaintext in their configuration tables pending the Phase 6 security gate.

## Extending the engine

A strategy supplies its name/version, a Pydantic configuration model, and a callable
from observation/config/protected-values to `AssertionOutcome`. Register it with
`AssertionRegistry`. Pack validation and orchestration use the registry, so a new
strategy needs no conditional branch in `EvaluationService`. The tests register
a new version-7 strategy and execute it through a real custom-pack API request.
Trusted extension code must return bounded, safe evidence; malformed results and
exceptions become errored assertions without exposing exception details.

The original deterministic helper API remains for compatibility; the production
engine uses the new assertion contract. Its legacy regex helper also uses the
bounded subprocess. Do not add unbounded regex calls when extending either path.

## Verification and remaining scope

See the Phase 1 completion record in [ROADMAP.md](ROADMAP.md). Tests cover real
adapter metadata, format 1 compatibility, version/config rejection, scoring and
mixed outcomes, timeout child cleanup, extension registration, secret redaction,
immutable historical snapshots, and SQLite/PostgreSQL upgrades/downgrades. Browser
checks exercise the report and a real format 2 demo run. Compose checks fresh
startup, persistence across recreation, outage recovery, and cascading deletion.

No hosted CI, cross-browser coverage, durable workers, production security review,
load benchmark, or detection-accuracy claim follows from these checks. Phases 2–3 are documented in [ASYNC_HISTORY.md](ASYNC_HISTORY.md). See [ADR-012](DECISIONS.md#adr-012--versioned-assertions-provenance-and-explicit-outcomes).
