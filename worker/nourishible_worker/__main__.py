from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .manifest import build_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Nourishible local evidence worker utilities")
    subcommands = parser.add_subparsers(dest="command", required=True)
    manifest = subcommands.add_parser("manifest", help="build a structured manifest from a confirmed capture")
    manifest.add_argument("capture_dir")
    manifest.add_argument("source_url")
    manifest.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.command == "manifest":
        result = build_manifest(args.capture_dir, args.source_url)
        with open(args.out, "w", encoding="utf-8") as output:
            json.dump(asdict(result), output, indent=2)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
