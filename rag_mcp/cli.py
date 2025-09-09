from __future__ import annotations

import argparse
import sys

from .ingest import (
    ingest_from_config,
    ingest_from_multi_config,
    ingest_collection_by_id,
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        "web-rag-cli", description="Ingest websites and build a local RAG index"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_ing = sub.add_parser(
        "ingest", help="Ingest websites from a YAML config and build index"
    )
    p_ing.add_argument(
        "--config",
        required=True,
        help="Path to YAML config with crawl + embedding settings",
    )
    p_ing.add_argument("--all", action="store_true", help="Ingest all collections")
    p_ing.add_argument("--collection", help="Ingest a specific collection")

    p_ing_multi = sub.add_parser(
        "ingest-multi", help="Ingest all collections from a YAML config"
    )
    p_ing_multi.add_argument(
        "--config",
        required=True,
        help="Path to YAML config with crawl + embedding settings",
    )

    p_ing_collection = sub.add_parser(
        "ingest-collection", help="Ingest a specific collection from a YAML config"
    )
    p_ing_collection.add_argument(
        "--config",
        required=True,
        help="Path to YAML config with crawl + embedding settings",
    )
    p_ing_collection.add_argument("--collection", help="Ingest a specific collection")

    args = p.parse_args(argv)
    if args.cmd == "ingest":
        if args.all:
            ingest_from_multi_config(args.config)
        elif args.collection:
            ingest_collection_by_id(args.config, args.collection)
        else:
            ingest_from_config(args.config)
        return 0
    elif args.cmd == "ingest-multi":
        ingest_from_multi_config(args.config)
        return 0
    elif args.cmd == "ingest-collection":
        ingest_collection_by_id(args.config, args.collection)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
