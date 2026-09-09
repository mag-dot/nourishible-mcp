"""Runtime orchestration that never begins capture without human confirmation."""
from __future__ import annotations

from typing import Callable, Optional

from .api import WorkerApi
from .spool import EncryptedSpool
from .types import Lease, WorkerCapabilities


HumanConfirmer = Callable[[Lease], bool]


class LocalWorkerRuntime:
    def __init__(self, api: WorkerApi, spool: EncryptedSpool, worker_id: str, capabilities: WorkerCapabilities):
        self.api, self.spool, self.worker_id, self.capabilities = api, spool, worker_id, capabilities

    def heartbeat(self, stage: str = "idle") -> None:
        self.api.heartbeat(self.worker_id, self.capabilities, stage)

    def accept_one_human_confirmed_job(self, confirm: HumanConfirmer) -> Optional[Lease]:
        """Claim at most one offer, retaining it only after a human accepts it.

        The callback is where the local UI displays the source URL and requires the
        operator to attest they personally opened and played that exact post. No browser
        action happens in this runtime.
        """
        lease = self.api.claim(self.worker_id)
        if lease is None:
            return None
        if not confirm(lease):
            self.api.release(self.worker_id, lease, "operator_declined_or_not_ready")
            return None
        self.spool.put(lease.attempt_id, {"lease": lease.to_wire(), "stage": "awaiting_human_capture"})
        self.heartbeat("awaiting_human_capture")
        return lease

    def complete_upload(self, lease: Lease, processing_job_id: str) -> None:
        self.spool.remove(lease.attempt_id)
        self.heartbeat("idle")
