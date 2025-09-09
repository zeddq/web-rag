from __future__ import annotations

import argparse
import sys

from .ingest import ingest_from_config


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser("web-rag-cli", description="Ingest websites and build a local RAG index")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_ing = sub.add_parser("ingest", help="Ingest websites from a YAML config and build index")
    p_ing.add_argument("--config", required=True, help="Path to YAML config with crawl + embedding settings")

    args = p.parse_args(argv)
    if args.cmd == "ingest":
        ingest_from_config(args.config)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

