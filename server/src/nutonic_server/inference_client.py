"""HTTP client for ``inference/*`` workers (IMP-092) — timeouts only until routes wire calls."""

from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class InferenceClientConfig:
    connect_timeout_s: float = 5.0
    read_timeout_s: float = 60.0
    write_timeout_s: float = 30.0


class InferenceClient:
    """Thin ``httpx`` wrapper for orchestrator → worker calls."""

    def __init__(
        self,
        *,
        config: InferenceClientConfig | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._config = config or InferenceClientConfig()
        self._owns_client = client is None
        timeout = httpx.Timeout(
            connect=self._config.connect_timeout_s,
            read=self._config.read_timeout_s,
            write=self._config.write_timeout_s,
        )
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def get_json(self, url: str) -> dict:
        r = self._client.get(url)
        r.raise_for_status()
        return r.json()

    def __enter__(self) -> InferenceClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
