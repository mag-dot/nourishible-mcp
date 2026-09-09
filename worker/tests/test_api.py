import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from nourishible_worker.api import HttpWorkerApi, WorkerProtocolError
from nourishible_worker.types import EvidenceFile, EvidenceManifest, Lease, WorkerCapabilities


ENDPOINTS = {name: name for name in (
    "enroll", "heartbeat", "claim", "resume", "release", "prepare_upload", "commit_evidence"
)}


class Response:
    def __init__(self, value):
        self.value = json.dumps(value).encode("utf-8")
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return self.value


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.api = HttpWorkerApi("https://worker.example/api/", ENDPOINTS, "token-1")

    def test_enroll_serializes_wire_payload_and_headers(self):
        captured = {}
        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.headers)
            captured["body"] = json.loads(req.data.decode("utf-8"))
            captured["timeout"] = timeout
            return Response({"workerId": "worker-1"})

        with patch("nourishible_worker.api.request.urlopen", fake_urlopen):
            result = self.api.enroll("Kitchen Mac", WorkerCapabilities(), "enroll-1")

        self.assertEqual("worker-1", result)
        self.assertEqual("https://worker.example/api/enroll", captured["url"])
        self.assertEqual("Bearer token-1", captured["headers"]["Authorization"])
        self.assertEqual("Kitchen Mac", captured["body"]["displayName"])
        self.assertEqual("instagram", captured["body"]["capabilities"]["platforms"][0])
        self.assertEqual("enroll-1", captured["body"]["enrollmentToken"])
        self.assertEqual(20, captured["timeout"])

    def test_claim_serializes_worker_header_and_lease(self):
        captured = {}
        lease = {"jobId": "job-1", "attemptId": "attempt-1", "fencingToken": "fence-1",
                 "sourceUrl": "https://instagram.com/reel/a", "expiresAt": "later"}
        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.headers)
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return Response({"lease": lease})

        with patch("nourishible_worker.api.request.urlopen", fake_urlopen):
            result = self.api.claim("worker-1")

        self.assertEqual(Lease.from_wire(lease), result)
        self.assertEqual("worker-1", captured["headers"]["X-nourishible-worker-id"])
        self.assertEqual({}, captured["body"])

    def test_missing_required_response_field_is_protocol_error(self):
        with patch("nourishible_worker.api.request.urlopen", return_value=Response({})):
            with self.assertRaisesRegex(WorkerProtocolError, "missing string field workerId"):
                self.api.enroll("Kitchen Mac", WorkerCapabilities(), "enroll-1")

    def test_commit_payload_contains_artifact_ids_but_not_local_paths(self):
        captured = {}
        lease = Lease("job-1", "attempt-1", "fence-1", "https://instagram.com/reel/a", "later")
        manifest = EvidenceManifest(
            source_url=lease.source_url,
            capture_method="operator_screen_capture",
            policy_version="instagram-human-capture-v1",
            human_action_at="2026-09-09T00:00:00+00:00",
            files=[EvidenceFile("frame", "/private/capture/frame_0001.jpg", "abc", 123, 4.0)],
            transcript_text="mix",
            onscreen_text="1 cup flour",
            caption_text="caption",
        )

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return Response({"processingJobId": "processing-1"})

        with patch("nourishible_worker.api.request.urlopen", fake_urlopen):
            result = self.api.commit_evidence("worker-1", lease, manifest, {
                "/private/capture/frame_0001.jpg": "artifact-1"
            })

        self.assertEqual("processing-1", result)
        payload = captured["body"]
        self.assertEqual("artifact-1", payload["manifest"]["files"][0]["artifactId"])
        self.assertNotIn("path", json.dumps(payload))

    def test_malformed_json_is_protocol_error(self):
        class BadResponse(Response):
            def __init__(self):
                self.value = b"not-json"
        with patch("nourishible_worker.api.request.urlopen", return_value=BadResponse()):
            with self.assertRaisesRegex(WorkerProtocolError, "returned non-JSON"):
                self.api.heartbeat("worker-1", WorkerCapabilities(), "idle")

    def test_http_error_is_protocol_error(self):
        exc = HTTPError("https://worker.example/api/claim", 409, "busy", {}, None)
        with patch("nourishible_worker.api.request.urlopen", side_effect=exc):
            with self.assertRaisesRegex(WorkerProtocolError, "claim rejected: HTTP 409"):
                self.api.claim("worker-1")
