"""HTTP adapter behind an explicit Phase-1-owned endpoint map.

No path is hard-coded here. Server and worker must agree on the typed payloads before
the map is configured, preventing a local package from silently inventing an API.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional, Protocol
from urllib import error, request

from .types import EvidenceManifest, Lease, WorkerCapabilities


class WorkerApi(Protocol):
    def enroll(self, display_name: str, capabilities: WorkerCapabilities, enrollment_token: str) -> str: ...
    def heartbeat(self, worker_id: str, capabilities: WorkerCapabilities, stage: str) -> None: ...
    def claim(self, worker_id: str) -> Optional[Lease]: ...
    def resume(self, worker_id: str, lease: Lease) -> Optional[Lease]: ...
    def release(self, worker_id: str, lease: Lease, reason: str) -> None: ...
    def prepare_upload(self, worker_id: str, lease: Lease, manifest: EvidenceManifest) -> Dict[str, Any]: ...
    def commit_evidence(self, worker_id: str, lease: Lease, manifest: EvidenceManifest,
                        artifact_ids: Dict[str, str]) -> str: ...


class WorkerProtocolError(RuntimeError):
    pass


class HttpWorkerApi:
    """Minimal dependency-free HTTP implementation of ``WorkerApi``.

    ``endpoint_map`` values are server-owned relative paths. Expected keys are documented
    in README; absent keys fail closed rather than falling back to guessed routes.
    """
    REQUIRED_ENDPOINTS = {"enroll", "heartbeat", "claim", "resume", "release", "prepare_upload", "commit_evidence"}

    def __init__(self, base_url: str, endpoint_map: Dict[str, str], bearer_token: Optional[str] = None):
        missing = self.REQUIRED_ENDPOINTS.difference(endpoint_map)
        if missing:
            raise WorkerProtocolError("missing Phase 1 endpoint mappings: " + ", ".join(sorted(missing)))
        self.base_url = base_url.rstrip("/")
        self.endpoint_map = endpoint_map
        self.bearer_token = bearer_token

    def _post(self, operation: str, payload: Dict[str, Any], worker_id: Optional[str] = None) -> Dict[str, Any]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if worker_id:
            headers["X-Nourishible-Worker-ID"] = worker_id
        if self.bearer_token:
            headers["Authorization"] = "Bearer " + self.bearer_token
        body = json.dumps(payload).encode("utf-8")
        endpoint = self.endpoint_map[operation]
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint
        req = request.Request(self.base_url + endpoint, body, headers, method="POST")
        try:
            with request.urlopen(req, timeout=20) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            raise WorkerProtocolError("%s rejected: HTTP %s" % (operation, exc.code)) from exc
        except error.URLError as exc:
            raise WorkerProtocolError("%s unavailable: %s" % (operation, exc.reason)) from exc
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise WorkerProtocolError("%s returned non-JSON" % operation) from exc
        if not isinstance(parsed, dict):
            raise WorkerProtocolError("%s returned a non-object response" % operation)
        return parsed

    @staticmethod
    def _required_string(result: Dict[str, Any], operation: str, key: str) -> str:
        value = result.get(key)
        if not isinstance(value, str) or not value:
            raise WorkerProtocolError("%s response is missing string field %s" % (operation, key))
        return value

    def enroll(self, display_name: str, capabilities: WorkerCapabilities, enrollment_token: str) -> str:
        result = self._post("enroll", {"displayName": display_name, "capabilities": capabilities.to_wire(),
                                        "enrollmentToken": enrollment_token})
        return self._required_string(result, "enroll", "workerId")

    def heartbeat(self, worker_id: str, capabilities: WorkerCapabilities, stage: str) -> None:
        self._post("heartbeat", {"capabilities": capabilities.to_wire(), "stage": stage}, worker_id)

    def claim(self, worker_id: str) -> Optional[Lease]:
        result = self._post("claim", {}, worker_id)
        if not result.get("lease"):
            return None
        try:
            return Lease.from_wire(result["lease"])
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkerProtocolError("claim response contains an invalid lease") from exc

    def resume(self, worker_id: str, lease: Lease) -> Optional[Lease]:
        result = self._post("resume", lease.to_wire(), worker_id)
        if not result.get("lease"):
            return None
        try:
            return Lease.from_wire(result["lease"])
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkerProtocolError("resume response contains an invalid lease") from exc

    def release(self, worker_id: str, lease: Lease, reason: str) -> None:
        self._post("release", {"lease": lease.to_wire(), "reason": reason}, worker_id)

    def prepare_upload(self, worker_id: str, lease: Lease, manifest: EvidenceManifest) -> Dict[str, Any]:
        return self._post("prepare_upload", {"lease": lease.to_wire(),
                                              "artifacts": manifest.upload_plan()}, worker_id)

    def commit_evidence(self, worker_id: str, lease: Lease, manifest: EvidenceManifest,
                        artifact_ids: Dict[str, str]) -> str:
        result = self._post("commit_evidence", {"lease": lease.to_wire(),
                                                   "manifest": manifest.to_wire(artifact_ids)}, worker_id)
        return self._required_string(result, "commit_evidence", "processingJobId")
