"""Typed, server-neutral protocol objects for the local worker boundary."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class WorkerCapabilities:
    platforms: List[str] = field(default_factory=lambda: ["instagram"])
    operations: List[str] = field(
        default_factory=lambda: ["human_screen_capture", "ocr", "local_transcription", "evidence_upload"]
    )
    forbidden: List[str] = field(
        default_factory=lambda: ["instagram_fetch", "browser_navigation", "browser_login", "autoplay", "batch_walk"]
    )
    max_concurrent_captures: int = 1
    screen_recording_permission: bool = False
    chrome_available: bool = False
    policy_version: str = "instagram-human-capture-v1"

    def to_wire(self) -> Dict[str, Any]:
        result = asdict(self)
        return {"maxConcurrentCaptures": result.pop("max_concurrent_captures"),
                "screenRecordingPermission": result.pop("screen_recording_permission"),
                "chromeAvailable": result.pop("chrome_available"),
                "policyVersion": result.pop("policy_version"), **result}


@dataclass(frozen=True)
class WorkerConfig:
    base_url: str
    display_name: str
    spool_path: str
    endpoint_map: Dict[str, str]
    worker_id: Optional[str] = None
    enrollment_token: Optional[str] = None


@dataclass(frozen=True)
class Lease:
    job_id: str
    attempt_id: str
    fencing_token: str
    source_url: str
    expires_at: str

    @classmethod
    def from_wire(cls, payload: Dict[str, Any]) -> "Lease":
        return cls(
            job_id=str(payload["jobId"]), attempt_id=str(payload["attemptId"]),
            fencing_token=str(payload["fencingToken"]), source_url=str(payload["sourceUrl"]),
            expires_at=str(payload["expiresAt"]),
        )

    def to_wire(self) -> Dict[str, str]:
        return {"jobId": self.job_id, "attemptId": self.attempt_id,
                "fencingToken": self.fencing_token, "sourceUrl": self.source_url,
                "expiresAt": self.expires_at}


@dataclass(frozen=True)
class EvidenceFile:
    kind: str
    path: str
    sha256: str
    bytes: int
    timestamp_seconds: Optional[float] = None

    def to_wire(self, artifact_id: str) -> Dict[str, Any]:
        data: Dict[str, Any] = {"kind": self.kind, "artifactId": artifact_id,
                                "sha256": self.sha256, "bytes": self.bytes}
        if self.timestamp_seconds is not None:
            data["timestampSeconds"] = self.timestamp_seconds
        return data


@dataclass(frozen=True)
class EvidenceManifest:
    source_url: str
    capture_method: str
    policy_version: str
    human_action_at: str
    files: List[EvidenceFile]
    transcript_text: str
    onscreen_text: str
    caption_text: str

    def upload_plan(self) -> List[Dict[str, Any]]:
        """Artifact descriptors for the server to issue upload slots.

        Local paths intentionally never cross the worker/server boundary.
        """
        return [{"kind": f.kind, "sha256": f.sha256, "bytes": f.bytes,
                 **({"timestampSeconds": f.timestamp_seconds} if f.timestamp_seconds is not None else {})}
                for f in self.files]

    def to_wire(self, artifact_ids: Dict[str, str]) -> Dict[str, Any]:
        return {
            "sourceUrl": self.source_url,
            "captureMethod": self.capture_method,
            "policyVersion": self.policy_version,
            "humanActionAt": self.human_action_at,
            "files": [f.to_wire(artifact_ids[f.path]) for f in self.files],
            "transcriptText": self.transcript_text,
            "onscreenText": self.onscreen_text,
            "captionText": self.caption_text,
        }
