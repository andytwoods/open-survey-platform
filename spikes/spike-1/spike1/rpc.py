"""Minimal LimeSurvey RemoteControl 2 JSON-RPC client (httpx)."""
from __future__ import annotations

import base64
import itertools
from typing import Any

import httpx

BASE = "http://localhost:8082"
RPC_URL = f"{BASE}/index.php?r=admin/remotecontrol"
ADMIN_USER = "admin"
ADMIN_PASSWORD = "spike1-local-admin-pw"  # local-only throwaway, see docker-compose.yml


class RPCError(RuntimeError):
    pass


class RC2:
    def __init__(self, url: str = RPC_URL) -> None:
        self.url = url
        self.http = httpx.Client(timeout=60)
        self._ids = itertools.count(1)
        self.key: str | None = None
        self.log: list[dict[str, Any]] = []

    def raw(self, method: str, *params: Any) -> Any:
        body = {"method": method, "params": list(params), "id": next(self._ids)}
        r = self.http.post(self.url, json=body, headers={"Content-Type": "application/json"})
        r.raise_for_status()
        data = r.json()
        self.log.append({"method": method, "error": data.get("error"),
                         "result_type": type(data.get("result")).__name__})
        if data.get("error"):
            raise RPCError(f"{method}: {data['error']}")
        return data["result"]

    def login(self) -> str:
        self.key = self.raw("get_session_key", ADMIN_USER, ADMIN_PASSWORD)
        if not isinstance(self.key, str):
            raise RPCError(f"login failed: {self.key}")
        return self.key

    def call(self, method: str, *params: Any) -> Any:
        if self.key is None:
            self.login()
        res = self.raw(method, self.key, *params)
        if isinstance(res, dict) and "status" in res and len(res) == 1 and res["status"] not in ("OK",):
            raise RPCError(f"{method}: {res['status']}")
        return res

    def close(self) -> None:
        if self.key:
            try:
                self.raw("release_session_key", self.key)
            except Exception:
                pass
        self.http.close()


def b64(s: str | bytes) -> str:
    return base64.b64encode(s.encode() if isinstance(s, str) else s).decode()


def unb64(s: str) -> bytes:
    return base64.b64decode(s)
