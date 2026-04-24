# PRO Mini-Apps Operations

## SLOs

- Create job route returns `queued` in under 500 ms for healthy control-plane dependencies.
- Poll route is read-only and should stay under 200 ms p95.
- Terminal job states are `completed`, `failed`, or `cancelled`; no job should remain `running` beyond the worker timeout budget without an operator alert.

## Alerts

- Queue depth above `pro_max_concurrent_jobs * 10` for 10 minutes.
- `worker_unreachable` or `worker_timeout` failures above 10% for 15 minutes.
- HMAC replay rejections above normal baseline.
- Artifact disk usage above 80% of the configured volume.

## Degraded Modes

- PRO materialization unavailable: jobs fail with `worker_unreachable`; UI should show retryable service-unavailable copy.
- TiM unavailable: profile jobs fail unless the profile explicitly supports brief-only mode.
- LFM briefing unavailable: analysis artifacts can still be shown; Brief Composer should display limited synthesis.

## Triage

1. Check `/api/v1/config` exposes `features.pro_jobs = true`.
2. Check worker `/health` endpoints and required/optional origin settings.
3. Inspect PRO job rows by status and `error_class`.
4. Verify inbound HMAC secrets match server outbound `InferenceClient` settings.
5. Confirm artifact root has free space and cleanup is running.
