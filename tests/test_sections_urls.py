import re

import pytest

from content_decay_finder import AnalysisConfig, analyze
from content_decay_finder.config import SectionRule
from content_decay_finder.urls import normalize_url, section_of, url_path
from synth import standard_dataset


@pytest.mark.parametrize(
    ("url", "depth", "section"),
    [
        ("https://e.example/", 1, "/"),
        ("https://e.example/about", 1, "/"),
        ("https://e.example/blog/post/", 1, "/blog/"),
        ("https://e.example/blog/2026/post", 1, "/blog/"),
        ("https://e.example/blog/2026/post", 2, "/blog/2026/"),
        ("https://e.example/blog/", 1, "/blog/"),
        ("https://e.example/shop/a/b/c/", 2, "/shop/a/"),
        ("https://e.example/shop/a/", 0, "/"),
        ("/relative/path", 1, "/relative/"),
    ],
)
def test_section_of(url, depth, section):
    assert section_of(url, depth) == section


def test_section_rules_win():
    rules = [SectionRule("Guides", re.compile(r"^/(guides|how-to)/"))]
    assert section_of("https://e.example/how-to/x/", 1, rules) == "Guides"
    assert section_of("https://e.example/blog/x/", 1, rules) == "/blog/"


def test_normalize_url():
    assert normalize_url("HTTPS://WWW.E.example/Path?a=1#frag") == "https://www.e.example/Path"
    assert normalize_url("https://e.example?x=1", strip_query=False) == "https://e.example/?x=1"
    assert normalize_url("not a url ") == "not a url"
    assert url_path("blog/x") == "/blog/x"


def test_section_summary(result):
    sections = {s.section: s for s in result.sections}
    blog = sections["/blog/"]
    assert blog.pages == 3 and blog.decaying == 2 and blog.growing == 1
    assert blog.lost_clicks > 0
    assert result.sections[0].section == "/blog/"  # sorted by lost clicks
    assert len(blog.weekly_clicks) == 16
    assert blog.top_pages[0].endswith("/blog/decaying-guide/")
    assert sections["/"].decay_share == 0


def test_custom_depth_and_rules():
    cfg = AnalysisConfig(section_rules=[SectionRule("Products", re.compile("^/products/"))])
    names = {s.section for s in analyze(standard_dataset(), cfg).sections}
    assert "Products" in names and "/products/" not in names
