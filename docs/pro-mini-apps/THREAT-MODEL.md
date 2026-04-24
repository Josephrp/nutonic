# PRO Mini-Apps Threat Model

## Request Integrity

Server-to-worker requests use `X-Nutonic-Timestamp`, `X-Nutonic-Nonce`, and `X-Nutonic-Signature`. Workers reject missing signatures, timestamps outside the skew window, invalid signatures, and replayed nonces within the nonce TTL/cache window.

The current canonical string is:

```text
{timestamp}
{nonce}
{method}
{path}
```

The request body is not included in the HMAC. Production deployments must rely on TLS inside the trusted service boundary for body integrity. If workers are exposed across untrusted networks, update the server and all workers together to include a request body hash in the canonical string.

## Session Isolation

PRO jobs are session-scoped. Poll, list, cancel, and artifact fetches must return `404` for jobs outside the caller session to avoid job enumeration.

## Claim Safety

OceanScout and other mini-app outputs are evidence summaries, not legal determinations. Briefs must surface confidence, limitations, and observation coverage before user-facing conclusions.

## Gameplay Boundary

PRO outputs are job-scoped by default. They must not mutate SCAN manifest truth, ranked state, or `AiGuessStore` rows unless a future OpenAPI contract adds an explicit map-bound publication path.
