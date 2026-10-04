from nethack_agent.menus import stair_here_from_tty


def _rows(*lines: str) -> tuple[bytes, ...]:
    width = max((len(line) for line in lines), default=80)
    return tuple(line.ljust(width).encode("latin1") for line in lines)


def test_stair_here_from_tty_finds_a_covered_downstairs_under_a_pile() -> None:
    rows = _rows(
        "                                    There is a staircase down here.",
        "                                    Things that are here:",
        "                                    a +0 dagger",
        "                                    a scroll labeled FOOBAR",
        "                                    --More--",
    )
    assert stair_here_from_tty(rows) == "staircase down here"


def test_stair_here_from_tty_finds_a_covered_upstairs() -> None:
    rows = _rows("There is a staircase up here.", "Things that are here:")
    assert stair_here_from_tty(rows) == "staircase up here"


def test_stair_here_from_tty_returns_none_for_an_ordinary_pile() -> None:
    rows = _rows(
        "Things that are here:",
        "a +1 long sword",
        "a +0 dagger",
        "--More--",
    )
    assert stair_here_from_tty(rows) is None


def test_stair_here_from_tty_returns_none_for_a_blank_screen() -> None:
    assert stair_here_from_tty(_rows("", "")) is None
