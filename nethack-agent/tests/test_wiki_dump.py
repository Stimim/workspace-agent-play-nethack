from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Load wiki_dump dynamically from the agents skill directory
_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "_agents"
    / "skills"
    / "nethack-wiki"
    / "scripts"
    / "wiki_dump.py"
)
_SPEC = importlib.util.spec_from_file_location("wiki_dump", _SCRIPT_PATH)
assert _SPEC and _SPEC.loader
wiki_dump = importlib.util.module_from_spec(_SPEC)
sys.modules["wiki_dump"] = wiki_dump
_SPEC.loader.exec_module(wiki_dump)


def _write_xml(
    path: Path, pages: list[tuple[str, str]], trailing_garbage: str = ""
) -> None:
    body = [
        '<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">',
        "  <siteinfo>",
        "    <sitename>NetHackWiki</sitename>",
        "    <case>first-letter</case>",
        "  </siteinfo>",
    ]
    for title, text in pages:
        body.append(
            f"  <page>\n"
            f"    <title>{title}</title>\n"
            f"    <revision><text>{text}</text></revision>\n"
            f"  </page>"
        )
    body.append(trailing_garbage)
    body.append("</mediawiki>")
    path.write_text("\n".join(body), encoding="utf-8")


def test_search_validates_entire_stream_and_catches_trailing_malformed_xml(
    tmp_path: Path,
) -> None:
    dump = tmp_path / "corrupt_trailing.xml"
    _write_xml(
        dump,
        [("Stairs", "Lead up or down."), ("Dungeon", "Dark place.")],
        trailing_garbage="<malformed><unclosed>",
    )

    with pytest.raises(RuntimeError, match="invalid MediaWiki XML"):
        wiki_dump.search(dump, "stair", include_text=False, limit=10)


def test_print_page_validates_entire_stream_and_catches_trailing_malformed_xml(
    tmp_path: Path,
) -> None:
    dump = tmp_path / "corrupt_trailing.xml"
    _write_xml(
        dump,
        [("Stairs", "Lead up or down."), ("Dungeon", "Dark place.")],
        trailing_garbage="<malformed><unclosed>",
    )

    with pytest.raises(RuntimeError, match="invalid MediaWiki XML"):
        wiki_dump.print_page(dump, "Stairs")


def test_search_respects_limit_while_validating_all_pages(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dump = tmp_path / "valid.xml"
    pages_data = [(f"Staircase {i}", f"Text {i}") for i in range(10)]
    _write_xml(dump, pages_data)

    ret = wiki_dump.search(dump, "staircase", include_text=False, limit=3)
    assert ret == 0
    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert lines == ["Staircase 0", "Staircase 1", "Staircase 2"]


def test_page_title_matching_policy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dump = tmp_path / "titles.xml"
    _write_xml(
        dump,
        [
            ("NetHack", "Original casing article."),
            ("Nethack", "Variant casing redirect."),
            ("Stairs", "Stairway guide."),
            ("Down staircase", "Detailed stairs article."),
        ],
    )

    # 1. Exact case match for distinct legal titles
    ret = wiki_dump.print_page(dump, "NetHack")
    assert ret == 0
    out = capsys.readouterr().out
    assert "Original casing article." in out

    ret = wiki_dump.print_page(dump, "Nethack")
    assert ret == 0
    out = capsys.readouterr().out
    assert "Variant casing redirect." in out

    # 2. First-letter normalization (MediaWiki first-letter convention)
    ret = wiki_dump.print_page(dump, "stairs")
    assert ret == 0
    out = capsys.readouterr().out
    assert "Stairway guide." in out

    # 3. Subsequent letters are case-sensitive: 'stAir' does not match 'Stairs'
    ret = wiki_dump.print_page(dump, "stAir")
    assert ret == 1
    err = capsys.readouterr().err
    assert "not found" in err

    # 4. Underscore / space equivalence in MediaWiki
    ret = wiki_dump.print_page(dump, "Down_staircase")
    assert ret == 0
    out = capsys.readouterr().out
    assert "Detailed stairs article." in out


def test_cli_catches_malformed_xml_and_prints_clean_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    dump = tmp_path / "corrupt_trailing.xml"
    _write_xml(
        dump,
        [("Stairs", "Lead up or down.")],
        trailing_garbage="<malformed><unclosed>",
    )

    monkeypatch.setattr(
        sys, "argv", ["wiki_dump.py", "--dump", str(dump), "search", "stair"]
    )
    ret = wiki_dump.main()
    assert ret == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "invalid MediaWiki XML" in captured.err

    monkeypatch.setattr(
        sys, "argv", ["wiki_dump.py", "--dump", str(dump), "page", "Stairs"]
    )
    ret = wiki_dump.main()
    assert ret == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "invalid MediaWiki XML" in captured.err
