import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nethack_agent.api import UI_CONTENT_SECURITY_POLICY, create_app
from nethack_agent.ollama import OllamaConfig
from nethack_agent.run_manager import RunManager

UI_DIR = Path(__file__).parents[1] / "src" / "nethack_agent" / "ui"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}


@pytest.fixture
def api(tmp_path: Path) -> TestClient:
    return TestClient(create_app(RunManager(tmp_path, OllamaConfig(model="test"))))


def _assert_ui_headers(response, suffix: str) -> None:  # type: ignore[no-untyped-def]
    assert response.status_code == 200
    assert response.headers["content-type"] == CONTENT_TYPES[suffix]
    assert response.headers["content-security-policy"] == UI_CONTENT_SECURITY_POLICY
    assert response.headers["x-content-type-options"] == "nosniff"


def test_csp_allows_only_same_origin_resources_and_no_inline_script() -> None:
    directives = dict(
        directive.strip().split(" ", 1)
        for directive in UI_CONTENT_SECURITY_POLICY.split(";")
    )
    assert directives["default-src"] == "'none'"
    for name in ("script-src", "style-src", "connect-src", "img-src"):
        assert directives[name] == "'self'"
    assert "unsafe" not in UI_CONTENT_SECURITY_POLICY
    assert directives["frame-ancestors"] == "'none'"


def test_index_and_every_referenced_module_are_served_with_csp(
    api: TestClient,
) -> None:
    index = api.get("/")
    _assert_ui_headers(index, ".html")

    referenced = re.findall(r'(?:src|href)="ui/([^"]+)"', index.text)
    assert {"app.js", "app.css"} <= set(referenced)
    pending = list(referenced)
    served: set[str] = set()
    while pending:
        name = pending.pop()
        if name in served:
            continue
        response = api.get(f"/ui/{name}")
        _assert_ui_headers(response, Path(name).suffix)
        served.add(name)
        if name.endswith(".js"):
            pending.extend(re.findall(r'from "\./([^"]+)"', response.text))

    shipped = {path.name for path in UI_DIR.iterdir() if path.name != "index.html"}
    assert served == shipped


@pytest.mark.parametrize(
    "name", ["missing.js", "..%2Fapi.py", "api.py", "%2E%2E%2F__init__.py"]
)
def test_unlisted_assets_are_not_served(api: TestClient, name: str) -> None:
    assert api.get(f"/ui/{name}").status_code == 404


def test_page_is_self_contained_and_never_parses_data_as_html() -> None:
    external = re.compile(r"\b(?:https?|wss?|ftp)://|=[\"']//|@import|url\(")
    for path in UI_DIR.iterdir():
        text = path.read_text(encoding="utf-8")
        assert not external.search(text), path.name
        if path.suffix == ".js":
            assert not re.search(
                r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(",
                text,
            ), path.name
    index = (UI_DIR / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", index)
    assert not re.search(r"\s(?:on[a-z]+|style)=", index)
