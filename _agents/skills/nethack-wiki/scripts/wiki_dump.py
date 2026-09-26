#!/usr/bin/env python3
"""Search and extract pages from a MediaWiki XML dump without loading it whole."""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DUMP = (
    REPOSITORY_ROOT
    / "docs"
    / "external"
    / "nethack-wiki-xml-dump"
    / "nethackwiki_current.xml"
)


@dataclass(frozen=True)
class Page:
    title: str
    text: str


def pages(path: Path) -> Iterator[Page]:
    try:
        context = ET.iterparse(path, events=("start", "end"))
        _, root = next(context)
        namespace_end = root.tag.find("}")
        namespace = root.tag[: namespace_end + 1] if namespace_end >= 0 else ""
        for event, element in context:
            if event != "end" or element.tag != f"{namespace}page":
                continue
            title = element.findtext(f"{namespace}title", default="")
            revision = element.find(f"{namespace}revision")
            text = ""
            if revision is not None:
                text = revision.findtext(f"{namespace}text", default="") or ""
            yield Page(title=title, text=text)
            element.clear()
            root.clear()
    except ET.ParseError as error:
        raise RuntimeError(f"invalid MediaWiki XML: {error}") from error


def search(path: Path, query: str, include_text: bool, limit: int) -> int:
    query_folded = query.casefold()
    matches = 0
    for page in pages(path):
        haystack = f"{page.title}\n{page.text}" if include_text else page.title
        if query_folded not in haystack.casefold():
            continue
        print(page.title)
        matches += 1
        if matches >= limit:
            break
    if matches == 0:
        print(f"No pages matched {query!r}.", file=sys.stderr)
        return 1
    return 0


def print_page(path: Path, title: str) -> int:
    title_folded = title.casefold()
    for page in pages(path):
        if page.title.casefold() != title_folded:
            continue
        print(f"# {page.title}\n")
        print(page.text)
        return 0
    print(f"Page {title!r} was not found.", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dump",
        type=Path,
        default=DEFAULT_DUMP,
        help=f"MediaWiki XML file (default: {DEFAULT_DUMP})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser("search", help="find matching page titles")
    search_parser.add_argument("query")
    search_parser.add_argument(
        "--in-text", action="store_true", help="also scan full page wikitext"
    )
    search_parser.add_argument("--limit", type=int, default=20)

    page_parser = subparsers.add_parser("page", help="print one exact-title page")
    page_parser.add_argument("title")
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    if not arguments.dump.is_file():
        print(
            f"Dump not found: {arguments.dump}\n"
            "See docs/external/nethack-wiki-xml-dump/README.md.",
            file=sys.stderr,
        )
        return 2
    if arguments.command == "search":
        if arguments.limit <= 0:
            print("--limit must be greater than zero.", file=sys.stderr)
            return 2
        return search(
            arguments.dump, arguments.query, arguments.in_text, arguments.limit
        )
    return print_page(arguments.dump, arguments.title)


if __name__ == "__main__":
    raise SystemExit(main())
