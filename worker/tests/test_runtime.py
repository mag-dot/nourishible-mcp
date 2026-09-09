import tempfile
import unittest
from pathlib import Path

from nourishible_worker.runtime import LocalWorkerRuntime
from nourishible_worker.spool import EncryptedSpool
from nourishible_worker.types import Lease, WorkerCapabilities


class MemorySecrets:
    def __init__(self):
        self.value = b"a" * 64
    def get_or_create(self, name):
        return self.value


class FakeApi:
    def __init__(self):
        self.lease = Lease("igjob_1", "attempt_1", "fence_1", "https://instagram.com/reel/a", "future")
        self.released = []
        self.heartbeats = []
    def heartbeat(self, worker_id, capabilities, stage):
        self.heartbeats.append(stage)
    def claim(self, worker_id):
        return self.lease
    def release(self, worker_id, lease, reason):
        self.released.append((lease, reason))


class RuntimeTests(unittest.TestCase):
    def test_decline_releases_without_spooling_or_capture(self):
        with tempfile.TemporaryDirectory() as temp:
            api = FakeApi()
            spool = EncryptedSpool(str(Path(temp) / "spool.db"), MemorySecrets())
            runtime = LocalWorkerRuntime(api, spool, "mag", WorkerCapabilities())
            self.assertIsNone(runtime.accept_one_human_confirmed_job(lambda _: False))
            self.assertEqual("operator_declined_or_not_ready", api.released[0][1])
            self.assertEqual([], spool.pending())

    def test_confirmation_spools_the_fenced_lease(self):
        with tempfile.TemporaryDirectory() as temp:
            api = FakeApi()
            spool = EncryptedSpool(str(Path(temp) / "spool.db"), MemorySecrets())
            runtime = LocalWorkerRuntime(api, spool, "mag", WorkerCapabilities())
            lease = runtime.accept_one_human_confirmed_job(lambda _: True)
            self.assertEqual("attempt_1", lease.attempt_id)
            self.assertEqual("fence_1", spool.pending()[0]["lease"]["fencingToken"])
