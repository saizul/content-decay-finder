"""Use content-decay-finder as a library (runs offline on the sample data)."""

from pathlib import Path

from content_decay_finder import AnalysisConfig, analyze, load_paths
from content_decay_finder.report import render_markdown

here = Path(__file__).parent
dataset = load_paths([here / "sample-data"])
result = analyze(dataset, AnalysisConfig(recent_weeks=4, baseline_weeks=8))

for page in result.ranked()[:5]:
    print(f"{page.priority:5.1f}  {page.page}  lost {page.lost_clicks:.0f} clicks  causes={','.join(page.causes)}")

for case in result.cannibalization:
    print("cannibalised:", case.query, [p.page for p in case.pages])

markdown = render_markdown(result)
print(markdown.splitlines()[0])
