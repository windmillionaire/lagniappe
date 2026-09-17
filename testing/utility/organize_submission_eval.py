"""Load synthetic file and form scenarios for the unified planner tests."""

import json
from pathlib import Path

CORPUS = Path(__file__).parents[1] / "files" / "organize_submission_eval.json"


def load_cases():
    """Return the retained grounded-value regression scenarios."""
    return json.loads(CORPUS.read_text(encoding="utf-8"))
