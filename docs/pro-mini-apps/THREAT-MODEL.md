# PRO Mini-Apps Threat Model

## Request Integrity

Server-to-worker requests use `X-Nutonic-Timestamp`, `X-Nutonic-Nonce`, `X-Nutonic-Content-SHA256`, and `X-Nutonic-Signature`. Workers reject missing signatures, body-hash mismatches, timestamps outside the skew window, invalid signatures, and replayed nonces within the nonce TTL/cache window.

The skew and in-process nonce cache cap are configurable with `NUTONIC_INFERENCE_HMAC_MAX_SKEW_SECONDS` and `NUTONIC_INFERENCE_HMAC_NONCE_CACHE_MAX` (or their non-prefixed `INFERENCE_*` aliases). The cache is process-local: multi-worker or multi-instance deployments still need sticky routing or a shared nonce store if replay resistance must hold across replicas. Treat the in-process cache as a single-worker guardrail, not a distributed replay ledger.

The current canonical string is:

```text
{timestamp}
{nonce}
{method}
{path}
{body_sha256}
```

The request body hash is always included in the HMAC canonical string. For bodyless requests, `body_sha256` is the SHA-256 of empty bytes.

## Session Isolation

PRO jobs are session-scoped. Poll, list, cancel, and artifact fetches must return `404` for jobs outside the caller session to avoid job enumeration.

## Claim Safety

OceanScout and other mini-app outputs are evidence summaries, not legal determinations. Briefs must surface confidence, limitations, and observation coverage before user-facing conclusions.

## Gameplay Boundary

PRO outputs are job-scoped by default. They must not mutate SCAN manifest truth, ranked state, or `AiGuessStore` rows unless a future OpenAPI contract adds an explicit map-bound publication path.
