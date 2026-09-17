"""Focused AI-report characterization coverage."""

import pytest

from lagniappe.core.tools.ai.reporting.proposals import selection
from lagniappe.core.tools.ai.reporting.execution import runner as report_runner
from testing.utility.ai_report_fakes import _fetch_one_from, _test_user
from testing.utility.test_entities import TestEntities
