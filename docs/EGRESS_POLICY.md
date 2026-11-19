# Outbound destination policy (P6-5)

Sentinel sends prompts and credentials to configured targets. Without a connection
policy, an API caller could use it to reach an internal service or cloud metadata
endpoint (server-side request forgery, SSRF). URL syntax validation alone cannot
stop that: a permitted hostname can resolve to a private address, or change its
answer between validation and connection.

Target HTTP requests now default to **denied**. A trusted installation operator
must grant each destination. Judge requests have a separate default grant for
`https://api.openai.com:443`, resolving only to public addresses. These rules are
not API fields, project roles, or proof that a target owner authorized testing.
Test only owned or explicitly authorized systems with synthetic data.

## Configuration and compatibility

The API and worker read two JSON-object environment settings (or `backend/.env`
for native development):

```sh
TARGET_EGRESS_RULES='{"https://owned.example.test":[]}'
JUDGE_EGRESS_RULES='{"https://api.openai.com":[]}'
```

Each key is an exact HTTP(S) **origin**: scheme, hostname/IP and port. Default
ports normalize to 80/443; hostnames normalize through HTTPX's URL parser. Paths,
queries, credentials, fragments, wildcard hosts and duplicate normalized origins
are rejected. A trailing slash is allowed. A grant applies to all paths/queries on
that origin. Subdomains, trailing-dot aliases, alternate ports and HTTP/HTTPS are
distinct. Prefer HTTPS; explicitly granting HTTP permits unencrypted transmission.

Each value is a list of **additional private CIDRs** for that origin. An empty list
allows only globally routable addresses. CIDRs must fit inside RFC1918 IPv4,
IPv6 ULA or loopback ranges, with no host bits. They do not permit arbitrary
special-use space or `0.0.0.0/0`. There are at most 64 origins and 16 CIDRs per
origin. Invalid policy fails settings validation. `{}` denies all origins,
including the judge provider when set for `JUDGE_EGRESS_RULES`.

For the native demo, set this in **both API and worker terminals**:

```sh
export TARGET_EGRESS_RULES='{"http://127.0.0.1:8001":["127.0.0.1/32"]}'
```

Register `http://127.0.0.1:8001/chat` or its security-fixture paths. `localhost`
requires its own origin and may need both `127.0.0.1/32` and `::1/128` if DNS
returns both. Granting loopback is a deliberate operator exception, not an
automatic consequence of development or unauthenticated local mode.

The local Compose configuration explicitly grants only `http://demo-target:8001`
with RFC1918 ranges to accommodate Docker's assigned bridge subnet. Override
`TARGET_EGRESS_RULES` in the root `.env` for other authorized targets. Overrides
replace the whole object; include the demo rule if still needed. Tighten the
CIDRs to the actual service network where practical. Compose forwards the same
rules to API and worker. Browser tests grant only their own loopback demo port;
unit fixtures grant only their exact ephemeral listeners.

Restart API/workers after policy changes. Settings are cached per process. No
schema migration is needed; head remains `0008_provider_credentials`. Existing
targets and accepted jobs are preserved, but execution can now be denied until
their destination is granted. Target registration remains syntactic: it does not
resolve DNS, probe a service or promise that execution is permitted.

## Enforcement and report behavior

1. Both production HTTP adapters use `EgressTransport`. Unknown origins fail
   before DNS, TCP, HTTP bodies or authorization headers are sent.
2. At TCP connection time the backend resolves A/AAAA addresses. It validates
   **every answer** before dialing; one denied address rejects the entire answer.
   Empty or more than 64 answers are denied. Resolver failures remain sanitized
   retryable transport errors.
3. Approved canonical numeric addresses are passed to the socket backend. The
   original hostname is not resolved a second time. HTTP Host, TLS SNI and
   certificate hostname verification still use the original hostname. Approved
   addresses may be tried in order within the remaining connection timeout.
4. Link-local, unspecified, multicast, reserved space, IPv4-mapped IPv6,
   well-known NAT64/6to4/Teredo ranges and known Azure/AWS special metadata
   addresses remain denied even with a private grant. Private/loopback addresses
   otherwise need their explicit CIDR. Public classification uses Python's
   `ipaddress` tables, so supported runtime patch changes need regression checks.
5. Each HTTP request has its own connection pool, so retries/new requests resolve
   and check again. Redirects remain disabled; environment proxies and ambient
   certificate overrides are not used. TLS uses the existing verified CA bundle.

Target denial is a non-retryable **execution error**, with the message
`Target destination is not permitted by operator policy.` Judge denial returns
`judge_destination_denied`, also non-retryable. Neither is a behavioral failure
or a successful security test. Existing report coverage/error presentation applies.
Error text omits URLs, addresses, query strings and secrets. Registered URLs and
historical snapshots are still visible as before; never put secrets in URLs.

Worker policy comes from its current trusted settings and is explicitly forwarded
through the restricted case/provider subprocess environment. It is **not frozen
into jobs** and is never accepted from the submitted target/pack/runtime payload.
After worker restart, policy tightening applies to previously accepted jobs while
their credentials/ownership remain frozen. Already transmitted requests cannot be
recalled. A cached judgment makes no new provider request; policy denial is not
checked for cache hits because no network connection occurs.

## Engineering choices and limits

The adapter uses HTTPX's transport interface and HTTPCore's documented custom
network backend. `httpcore==1.0.9`, already in the locks through HTTPX, is now a
direct dependency because Sentinel imports it. Lock regeneration changed no
resolved packages. No custom TLS implementation, global socket monkeypatch,
public destination-management API or database migration was introduced.

Per-request pools trade connection reuse for straightforward connection-time
enforcement. No performance benefit is claimed. System DNS resolution itself has
no reliable Python socket deadline; existing queued case/provider subprocess
deadlines bound those execution paths. The deprecated synchronous local endpoint
still lacks an overall process deadline. Decoding/memory/request-body limits are
separate unfinished work.

This is an **application HTTP policy**, not a host/container firewall. It does not
control database/DNS connections, trusted host code, an allowed target's own
outbound requests, unusual operator-configured network translation/routing, or
compromised processes. Installation-wide grants are shared across projects;
project-specific network entitlements are not implemented. An approved service
must not itself expose an arbitrary proxy/fetch API. Keep narrow grants and add
infrastructure egress restrictions before public deployment.

Tests use synthetic inputs, fake DNS/socket streams and owned IPv4/IPv6/TLS
listeners. They cover rebinding, mixed answers, metadata/private addresses,
origin/port confusion, redirects/proxies, certificate/hostname verification,
current policy on queued work, provider isolation and sanitized errors. Browser
and Compose checks cover permitted demos and denied destinations. See the
[roadmap](ROADMAP.md#p6-5--outbound-destination-policy-2026-11-18) for actual results.
Live OpenAI calibration remains deferred. Phase 6 and its full security review
remain unfinished; public deployment remains prohibited.

Design references: [OWASP SSRF prevention](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)
and [HTTPCore network backends](https://www.encode.io/httpcore/network-backends/).
