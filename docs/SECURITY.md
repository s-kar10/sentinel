# Security model and limitations

Status: local MVP with Phases 1–5 (live judge calibration pending); initial audit 2026-09-14. This is a code-based risk inventory,
not a completed penetration test, dependency audit, or certification.

## Intended use and boundaries

Sentinel tests AI systems the developer owns or has explicit permission to test.
Use synthetic data and fake/scoped test credentials. The included demo deliberately
leaks public fake values and must never be exposed as a production AI application.

The MVP has no authentication, authorization, or tenant isolation. Run it only in a
trusted local environment. Compose publishes services on `127.0.0.1`, but that
does not protect against untrusted processes on the host or all container-network
access. Do not expose the API, database, or demo publicly before the security gate
in [ROADMAP.md](ROADMAP.md), Phase 6.

Trust boundaries are: browser/client → Sentinel API → database → worker → case process;
case process (or legacy API route) → configured target over HTTP; target output → parser/evaluator/storage → browser report.
Credentials, canaries, endpoint URLs, templates, and responses can be sensitive.

## Controls already present

- Pydantic validates URL schemes, field sizes, JSON-object templates, path syntax,
  and merged request mappings. Embedded URL username/password is rejected.
- Evaluation preflight requires a non-blank target canary for suites that use
  protected values. Rejected runs create no records and send no target requests.
  Path conversion failures are normalized and recorded per case rather than
  unexpectedly aborting the whole run.
- Target management schemas omit API-key contents and expose only key presence.
  Canary management returns masked display hints (prefix/suffix for longer values),
  not the full value. Masking still reveals information and is not encryption.
- Custom packs validate versions, IDs, evaluator allowlists, expected-value coverage,
  and bounded collections/fields before run creation or target contact. Custom
  executable/imported definitions are not accepted. Format 2 regex/schema checks
  use isolated children with input/time limits and a restricted schema profile. The 65,536-byte
  normalized pack limit runs after JSON parsing, not before body allocation.
- Selected validation inputs (`api_key`, `value`, `endpoint_url`, `attack_pack`, `versions`) are redacted.
  SQLAlchemy hides bound parameters. Expected transport errors use generic text
  rather than upstream exception content.
- httpx disables redirects and environment proxy settings, applies operation
  timeouts, and enforces a response-size cap while reading decoded chunks.
- JSON path traversal does not execute expressions. Target output is evaluated as
  text and rendered through React text nodes in `<pre>` elements, not injected HTML.
- ORM queries use structured SQLAlchemy expressions. SQLite tests enable foreign
  keys; Compose uses PostgreSQL with a local named volume.
- Backend/demo containers run as non-root users; Compose host ports bind loopback.
- Readiness failures return a generic 503 without database credentials, SQL, or
  driver exception details. The probe reads the recorded migration revision and
  does not repair schema. Its connection/pool/query limits are not a complete
  network deadline or denial-of-service defense.

- New stored evidence/snapshots redact known target credentials/canaries. Matching
  occurs before redaction; encoded/paraphrased secrets and historical text are not
  scrubbed. Redaction is not a general sensitive-data classifier.
- Queued runs have atomic submission, idempotency, case leases/fencing, fixed
  concurrency/admission limits, bounded attempts/deadlines and cancellation. Case
  children receive private input through pipes and generic failures hide tracebacks.
  These controls apply to the queued path, not the deprecated synchronous endpoint.
- Public job APIs omit private payloads and compatibility fingerprints. Active
  payloads contain plaintext copied secrets and are cleared on terminal state.
  Version labels containing known secrets are rejected before submission commits.
- Optional OpenAI judging is disabled by default, model-allowlisted by server
  configuration and uses a fixed provider URL. Known secrets are redacted before
  sending target evidence; no tools or redirects are enabled. Input/output limits,
  provider subprocess deadlines and strict result validation constrain execution.
  These controls do not establish judgment correctness or defeat prompt injection.
  Unrecognized sensitive content can still be transmitted to OpenAI.
- Active queued semantic jobs also contain a copied plaintext OpenAI key; terminal
  cleanup does not remove backups. The disposable local cache stores redacted
  judgments, expires entries after 24 hours and is not tenant-aware. Target deletion
  does not immediately clear that separate cache. Delete its file for immediate
  local cache removal. See [LLM_EVALUATION.md](LLM_EVALUATION.md) for full limits.

These controls reduce specific risks. They do not establish end-to-end secrecy,
bounded resource use, safe arbitrary outbound access, or production readiness.

## Synthetic security fixtures

[Phase 5 packs](SECURITY_PACKS.md) add explicit user/retrieval/tool trust-boundary
examples. `/security/safe` and `/security/vulnerable` are deterministic fixtures,
not defensive application templates. Only fixed synthetic tool arguments are
accepted. Their action records never trigger file, process or network operations;
render intents are data. The safe fixture is not a prompt-injection defense model.
Adapters for real applications require separate authorization, synthetic data,
trusted action instrumentation and controlled tools. These fixture constraints do
not restrict Sentinel's configured outbound target URLs or establish a security
review. Public deployment remains blocked on Phase 6.

## Risk register

| Risk | Current exposure | Required direction / gate |
| --- | --- | --- |
| SSRF and internal network access | Any accepted HTTP(S) target can address backend-reachable services; no DNS/IP/port allowlist or egress enforcement | Before public/multi-user use: explicit authorized destinations, IPv4/IPv6 and DNS rebinding defenses, connection-time enforcement, metadata/private-network policy, and network egress restrictions. Preserve local demo access through an explicit development policy |
| Unauthenticated access | Anyone reaching the API can configure targets, run requests, read reports, or cascade-delete data | Users, roles, tenant isolation, scoped API tokens, authorization on every API and job path |
| Plaintext secrets | API keys, canaries and active job payloads are plaintext in the database/backups | Encryption or secret-manager references, key isolation, least privilege, rotation/revocation, audit access |
| Sensitive evidence | New evidence redacts known keys/canaries; other sensitive content, encodings and old raw records can remain | Redaction/retention policy, scoped evidence access, safe exports, deletion/backup policy. Write-only key fields do not protect copies in target output |
| Secrets in other fields/errors | Templates and URL query strings are readable; validation redaction is field-specific, not comprehensive | Treat all input/output surfaces as potential secrets; use synthetic tests to cover validation, exceptions, logs, and UI. Do not place real secrets in templates/URLs |
| Request/response resource exhaustion | No application request-body or template depth limit; response cap is checked after decoding/chunk allocation; queued cases/runs now have deadlines; memory/decompression/input allocation is not fully bounded | Bounded input, parser/decompression safeguards, total deadlines, concurrency/rate limits and quotas |
| Run/API abuse | Queue limits/cancellation/idempotency exist, but queued submission count is unbounded and the deprecated synchronous route bypasses queue controls | Gate every execution path, bound queue size and add authenticated tenant budgets before exposure |
| Regex execution cost | Format 2 regex/schema use bounded isolated children; process scheduling/startup and overall resource usage remain operational concerns | Retain limits and measure workloads; expand schema features only with resource/security review |
| Database operations | P0-2 adds versioned migrations, guarded legacy adoption, startup revision checks, and documented/tested backup/restore procedures; target deletion still cascades history | Run migrations during a controlled maintenance window; protect backups and validate restoration. Automated production backup/recovery remains required before hosting |
| Dependency/container vulnerabilities | P0-3 adds hash-checked Python locks and a tested update workflow. A point-in-time npm audit found three affected packages, patched within existing ranges; the repeated npm audit reported zero findings. Python/container vulnerability scanning is still unverified | Establish repeatable scanning and release maintenance; hashes and passing tests do not establish package safety |
| False assurance | P0-1 blocks runs missing required canaries, but configured canaries may not actually exist in the target; historical empty-canary scores remain. Original scores still count non-passes equally; weighted scores exclude errors and require coverage. Comparisons are descriptive; substring checks miss semantic leakage | Read coverage/sample sizes; rerun/review mixed outcomes; no significance or comprehensive security claim |
| Judge/tool risks | Optional OpenAI judge; fixed provider URL, separated instructions/evidence, no tools, validated bounded output and known-secret redaction. Live model calibration is pending. No target tool-execution framework yet. | Rubric/injection/bias testing and human review remain necessary; structured output does not guarantee trustworthy judgments |

The target-client cap defaults to 1,000,000 bytes and is configurable in backend
settings. The Compose file does not currently forward `TARGET_MAX_RESPONSE_BYTES`
from the host environment. A slow stream can satisfy per-read timeouts, but queued child processes have an
overall attempt deadline. The synchronous compatibility path has no such deadline, and decompression can allocate data before the accumulated-size check.
Do not describe these mechanisms as a complete DoS defense. Queue leases constrain
admitted work, not external side effects during arbitrary process pauses or network
partitions. At-least-once retries may repeat requests. Use repeat-safe, authorized
targets. Shared database clocks must agree; multi-host fault tolerance is unverified.
Baselines are append-only through the API, not tamper-proof against DB administrators;
target deletion cascades history. Analysis cannot verify user-supplied version labels.

## Before public deployment

The P0-3 frontend lock update covers Vite 6.4.5, source-map-js 1.2.2, and
brace-expansion 1.1.21/5.0.12. Relevant advisory evidence includes
[Vite/launch-editor](https://github.com/advisories/GHSA-587h-7wmj-h5pm),
[source-map-js](https://github.com/advisories/GHSA-68fv-2mgg-jv7q), and
[brace-expansion](https://github.com/advisories/GHSA-qhr7-859c-m2p7).
The successful frontend lint/type/build checks are compatibility evidence, not
browser coverage or a complete vulnerability review.

Phase 6 must verify authentication, authorization, tenant separation, secret
storage/rotation, safe evidence handling, outbound destination enforcement, and
abuse controls. Phase 10 adds tested TLS, private service networking, managed
credentials, migration/backup/restore, deployment rollback, and operational
ownership. Review concrete implementations and test negative cases; a diagram or
checklist does not satisfy the gate.

Any deliberate access to internal development targets must be narrowly configured.
Arbitrary configured targets must never become an unrestricted production internal
network scanner. Never run security probes against third-party systems merely to
demonstrate Sentinel.

## Reporting and handling findings

Record reproducible development findings with synthetic data and identify the
affected source/behavior. Do not include real credentials or private target
responses in public issues. An external security contact and private reporting
channel have not been established; Phase 13 must define them before inviting
outside vulnerability reports. No disclosure SLA or security support commitment
has been established.
