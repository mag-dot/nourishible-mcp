# Nourishible local worker (Phase 2)

This package is the local, outbound-only half of the Instagram evidence flow. It is
intentionally **not** an Instagram downloader, scraper, browser driver, recipe
structurer, or recipe writer. The server owns job state and runs the existing
`structureAndSave()` pipeline after it accepts evidence.

The worker can only capture content that an operator has already opened and played in
their ordinary Chrome profile. `capture-worker.sh` deliberately unsets `AUTO_YES` and
keeps the preview confirmation in `capture-only.sh`; it never opens a URL or presses
play. One invocation is one human-confirmed post.

## Integration boundary

Phase 1 must supply the endpoint map and server implementation. This package does not
assume route names: `HttpWorkerApi` receives an explicit map for `enroll`, `heartbeat`,
`claim`, `resume`, `prepare_upload`, `commit_evidence`, and `release`. The JSON request
and response types in `nourishible_worker/types.py` are the contract to reconcile before
enabling the runtime.

The worker writes only encrypted attempt metadata to its local SQLite spool. Raw video is
never spooled by this package; capture evidence remains in the capture directory until
the upload/retention policy removes it. The encryption key lives in the macOS Keychain;
the worker fails closed if it cannot retrieve one.

Run its dependency-free unit tests with:

```bash
cd worker
./run-tests.sh
```

The same test runner works from the repository root:

```bash
worker/run-tests.sh
```

The package can be built from either directory with `python3 -m pip install .` (or
`python3 -m pip install -e .` for development). Build output, virtual environments,
Python caches, and macOS metadata are ignored by the repository.

This is intentionally a package source tree, not yet part of the user-facing skill
archive. It needs server endpoint review and an operator enrollment UX before release.
