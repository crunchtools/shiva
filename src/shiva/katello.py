"""Katello host collections as Shiva groups."""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from shiva.config import ConfigError, read_secret

PER_PAGE = 100
REQUEST_TIMEOUT = 30.0


class KatelloError(Exception):
    """Raised when the Katello API cannot answer."""


@dataclass
class KatelloClient:
    url: str
    username: str
    password: str
    verify: bool | str = True
    transport: httpx.BaseTransport | None = None

    @classmethod
    def from_env(cls) -> KatelloClient | None:
        """Build a client from KATELLO_* variables, or None when unconfigured."""
        url = os.environ.get("KATELLO_URL")
        if not url:
            return None
        username = os.environ.get("KATELLO_USERNAME")
        password = read_secret("KATELLO_PASSWORD")
        if not username or not password:
            raise ConfigError("KATELLO_URL is set but KATELLO_USERNAME or KATELLO_PASSWORD is not")
        verify: bool | str = os.environ.get("KATELLO_CA_BUNDLE") or True
        return cls(url=url.rstrip("/"), username=username, password=password, verify=verify)

    def __repr__(self) -> str:
        return f"KatelloClient(url={self.url!r}, username={self.username!r})"

    def _paged(self, path: str, params: dict[str, str]) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        page = 1
        with httpx.Client(
            base_url=self.url,
            auth=(self.username, self.password),
            verify=self.verify,
            timeout=REQUEST_TIMEOUT,
            transport=self.transport,
        ) as client:
            while True:
                query = {**params, "page": str(page), "per_page": str(PER_PAGE)}
                try:
                    response = client.get(path, params=query)
                    response.raise_for_status()
                    body = response.json()
                except httpx.HTTPStatusError as exc:
                    code = exc.response.status_code
                    raise KatelloError(f"Katello returned HTTP {code} for {path}") from None
                except (httpx.HTTPError, ValueError) as exc:
                    raise KatelloError(f"Katello request to {path} failed: {exc}") from None
                batch = body.get("results", [])
                results.extend(batch)
                total = int(body.get("subtotal", body.get("total", 0)) or 0)
                if not batch or len(results) >= total:
                    return results
                page += 1

    def host_collections(self) -> list[str]:
        rows = self._paged("/katello/api/host_collections", {})
        return sorted(str(row["name"]) for row in rows)

    def hosts_in_collection(self, name: str) -> list[str]:
        escaped = name.replace('"', '\\"')
        rows = self._paged("/api/v2/hosts", {"search": f'host_collection = "{escaped}"'})
        return [str(row["name"]) for row in rows]
