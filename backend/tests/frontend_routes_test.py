from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
STATIC_DIR = ROOT_DIR / "static"


class IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        element_id = attributes.get("id")
        if element_id:
            self.ids.append(element_id)


def main() -> int:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")

    parser = IdCollector()
    parser.feed(html)
    duplicate_ids = sorted({item for item in parser.ids if parser.ids.count(item) > 1})
    assert not duplicate_ids, f"duplicate HTML ids: {duplicate_ids}"

    expected_routes = {
        "dashboard": ["stage-dashboard"],
        "projects": ["stage-projects"],
        "knowledge": ["stage-kb", "stage-search"],
        "templates": ["stage-templates"],
        "settings": ["stage-ai", "stage-enterprise"],
        "operations-intake": ["stage-wizard", "stage-channel", "stage-starter", "stage-intake", "stage-communications"],
        "operations-finance": ["stage-pricing", "stage-pricing-rules", "stage-confirmation", "stage-payments"],
        "operations-delivery": ["stage-command", "stage-orders", "stage-delivery", "stage-delivery-assistant", "stage-client-confirm", "stage-feedback", "stage-closure"],
        "operations-assets": ["stage-case-assets", "stage-timeline", "stage-retro", "stage-project-retro"],
        "project-overview": ["stage-overview", "stage-workflow", "stage-task", "stage-materials"],
        "project-tender": ["stage-source", "stage-profile"],
        "project-outline": ["stage-strategy", "stage-plan"],
        "project-editor": ["stage-search", "stage-generate"],
        "project-visuals": ["stage-rich-document"],
        "project-review": ["stage-workflow", "stage-polish"],
        "project-delivery": ["stage-final", "stage-document-settings", "stage-delivery"],
    }
    html_ids = set(parser.ids)
    for route, section_ids in expected_routes.items():
        assert re.search(rf'^[ ]{{2}}["\']?{re.escape(route)}["\']?:\s*{{', script, re.MULTILINE), route
        for section_id in section_ids:
            assert section_id in html_ids, f"{route} references missing section {section_id}"
            assert f'"{section_id}"' in script, f"{route} does not map {section_id}"

    for page in ("overview", "tender", "outline", "editor", "visuals", "review", "delivery"):
        assert f'data-route-link="project-{page}"' in html
    for page in ("intake", "finance", "delivery", "assets"):
        assert f'href="#/operations/{page}"' in html

    assert '.layout > section.route-active' in styles
    assert '.mode-switch[hidden]' in styles
    assert '@media (max-width: 980px)' in styles
    assert 'grid-template-columns: minmax(0, 1fr)' in styles
    assert 'location.hash = `#/projects/${tenderId}/overview`' in script

    print(f"frontend routes ok: {len(expected_routes)} routes, {len(parser.ids)} unique ids")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
