"""Focused AI-report characterization coverage."""

import pytest

from lagniappe.core.tools.ai.reporting.proposals import validation


# @matrix ai-report : no-category page-form validation
@pytest.mark.unit
def test_validate_proposal_accepts_add_form_to_page_without_category():
    proposal = {
        "summary": "Create a property-tax form and add it to the existing page.",
        "confidence": 0.9,
        "actions": [
            {
                "id": "property_tax_form",
                "type": "create_form",
                "data": {
                    "name": "Property Tax Record",
                    "form_type": "page",
                    "schema": [
                        {
                            "id": "input-apn",
                            "type": "input",
                            "input": "text",
                            "title": "Assessor Parcel Number",
                        }
                    ],
                },
            },
            {
                "id": "add_property_tax_form",
                "type": "add_form_to_page",
                "depends_on": ["property_tax_form"],
                "data": {
                    "page": "existing-property-tax-page",
                    "form_action": "property_tax_form",
                },
            },
        ],
    }

    assert validation.validate_proposal(proposal) is proposal
