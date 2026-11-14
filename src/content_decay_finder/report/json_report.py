from __future__ import annotations

import json

from content_decay_finder.analyze import AnalysisResult


def render_json(result: AnalysisResult) -> str:
    return json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n"
