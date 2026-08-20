"""Example data used in AI prompt few-shot examples."""

CATEGORY_EXAMPLE = {
    "category_name": "Books",
    "category_description": "A collection of individual book records.",
    "form_name": "Book Details",
    "form_schema": [
        {
            "id": "input-author",
            "input": "text",
            "title": "Author",
            "type": "input",
        },
        {
            "id": "input-publication-year",
            "input": "number",
            "title": "Publication Year",
            "type": "input",
        },
    ],
}

CATEGORY_CONTEXT_EXAMPLE = {
    "category_name": "Learning",
    "category_description": (
        "A shared context for different academic and activity subjects."
    ),
}

WOODWORKING_PROJECT_EXAMPLE = {
    "project_name": "Custom Woodworking Project",
    "project_description": "End-to-end process for planning, designing, and building custom woodworking pieces from initial concept through finishing",
    "model_tasks": [
        {
            "name": "Design & Planning",
            "form_schema": [
                {
                    "id": "input-a1b2c3d4",
                    "type": "input",
                    "input": "text",
                    "title": "Project Name",
                    "required": True,
                },
                {
                    "id": "select-e5f6g7h8",
                    "type": "select",
                    "title": "Project Type",
                    "options": [
                        {"label": "Furniture", "value": "f1u2r3n4"},
                        {"label": "Cabinetry", "value": "c5a6b7i8"},
                        {"label": "Decorative", "value": "d9e0c1o2"},
                        {"label": "Storage", "value": "s3t4o5r6"},
                    ],
                    "required": True,
                },
                {
                    "id": "textarea-i9j0k1l2",
                    "type": "textarea",
                    "title": "Design Notes",
                    "placeholder": "Describe the overall design concept, style, and key features",
                },
                {
                    "id": "input-m3n4o5p6",
                    "type": "input",
                    "input": "text",
                    "title": "Dimensions (L x W x H)",
                    "placeholder": 'e.g., 24" x 12" x 36"',
                    "required": True,
                },
                {
                    "id": "select-q7r8s9t0",
                    "type": "select",
                    "title": "Skill Level Required",
                    "options": [
                        {"label": "Beginner", "value": "b1e2g3i4"},
                        {"label": "Intermediate", "value": "i5n6t7e8"},
                        {"label": "Advanced", "value": "a9d0v1a2"},
                    ],
                },
            ],
        },
        {
            "name": "Material Planning",
            "form_schema": [
                {
                    "id": "table-u1v2w3x4",
                    "type": "table",
                    "title": "Wood Materials",
                    "columns": [
                        {
                            "id": "row-y5z6a7b8",
                            "type": "input",
                            "input": "text",
                            "title": "Wood Type",
                        },
                        {
                            "id": "row-c9d0e1f2",
                            "type": "input",
                            "input": "text",
                            "title": "Dimensions Needed",
                        },
                        {
                            "id": "row-g3h4i5j6",
                            "type": "input",
                            "input": "number",
                            "title": "Board Feet",
                        },
                    ],
                },
                {
                    "id": "table-k7l8m9n0",
                    "type": "table",
                    "title": "Hardware & Supplies",
                    "columns": [
                        {
                            "id": "row-o1p2q3r4",
                            "type": "input",
                            "input": "text",
                            "title": "Item",
                        },
                        {
                            "id": "row-s5t6u7v8",
                            "type": "input",
                            "input": "number",
                            "title": "Quantity",
                        },
                        {"id": "row-w9x0y1z2", "type": "checkbox", "title": "In Stock"},
                    ],
                },
                {
                    "id": "input-a3b4c5d6",
                    "type": "input",
                    "input": "number",
                    "title": "Estimated Total Cost",
                    "placeholder": "Materials cost estimate",
                },
            ],
        },
        {
            "name": "Construction",
            "form_schema": [
                {
                    "id": "table-e7f8g9h0",
                    "type": "table",
                    "title": "Construction Steps",
                    "columns": [
                        {
                            "id": "row-i1j2k3l4",
                            "type": "input",
                            "input": "text",
                            "title": "Step Description",
                        },
                        {
                            "id": "row-m5n6o7p8",
                            "type": "input",
                            "input": "date",
                            "title": "Date Completed",
                        },
                        {"id": "row-q9r0s1t2", "type": "checkbox", "title": "Complete"},
                    ],
                },
                {
                    "id": "textarea-u3v4w5x6",
                    "type": "textarea",
                    "title": "Build Notes",
                    "placeholder": "Document any challenges, modifications, or lessons learned",
                },
            ],
        },
        {
            "name": "Finishing",
            "form_schema": [
                {
                    "id": "select-y7z8a9b0",
                    "type": "select",
                    "title": "Finish Type",
                    "options": [
                        {"label": "Polyurethane", "value": "p1o2l3y4"},
                        {"label": "Danish Oil", "value": "d5a6n7i8"},
                        {"label": "Shellac", "value": "s9h0e1l2"},
                        {"label": "Lacquer", "value": "l3a4c5q6"},
                        {"label": "Wax", "value": "w7a8x9f0"},
                    ],
                    "required": True,
                },
                {
                    "id": "input-c1d2e3f4",
                    "type": "input",
                    "input": "number",
                    "title": "Number of Coats Applied",
                },
                {
                    "id": "textarea-g5h6i7j8",
                    "type": "textarea",
                    "title": "Finishing Notes",
                    "placeholder": "Sanding grits used, drying times, final results",
                },
            ],
        },
    ],
}

VENDOR_EVALUATION_PROJECT_EXAMPLE = {
    "project_name": "Vendor Evaluation Process",
    "project_description": "Comprehensive vendor assessment process from initial discovery through contract negotiation and onboarding",
    "model_tasks": [
        {
            "name": "Initial Research",
            "form_schema": [
                {
                    "id": "input-v1e2n3d4",
                    "type": "input",
                    "input": "text",
                    "title": "Vendor Name",
                    "required": True,
                },
                {
                    "id": "select-c5a6t7e8",
                    "type": "select",
                    "title": "Vendor Category",
                    "options": [
                        {"label": "Software/SaaS", "value": "s1o2f3t4"},
                        {"label": "Professional Services", "value": "p5r6o7s8"},
                        {"label": "Hardware/Equipment", "value": "h9a0r1d2"},
                        {"label": "Marketing/Agency", "value": "m3a4r5k6"},
                        {"label": "Facilities/Operations", "value": "f7a8c9i0"},
                    ],
                    "required": True,
                },
                {
                    "id": "link-w1e2b3s4",
                    "type": "link",
                    "location": "out",
                    "title": "Vendor Website",
                },
                {
                    "id": "textarea-i5n6i7t8",
                    "type": "textarea",
                    "title": "Initial Assessment",
                    "placeholder": "First impressions, key capabilities, potential fit",
                },
                {
                    "id": "select-s9o0u1r2",
                    "type": "select",
                    "title": "How Did We Find Them",
                    "options": [
                        {"label": "Referral", "value": "r3e4f5e6"},
                        {"label": "Online Search", "value": "o7n8l9i0"},
                        {"label": "Industry Event", "value": "i1n2d3u4"},
                        {"label": "Cold Outreach", "value": "c5o6l7d8"},
                        {"label": "Existing Relationship", "value": "e9x0i1s2"},
                    ],
                },
            ],
        },
        {
            "name": "Capability Assessment",
            "form_schema": [
                {
                    "id": "table-c3a4p5a6",
                    "type": "table",
                    "title": "Requirements Evaluation",
                    "columns": [
                        {
                            "id": "row-r7e8q9u0",
                            "type": "input",
                            "input": "text",
                            "title": "Requirement",
                        },
                        {
                            "id": "row-m1e2t3s4",
                            "type": "checkbox",
                            "title": "Vendor Meets",
                        },
                        {
                            "id": "row-n5o6t7e8",
                            "type": "input",
                            "input": "text",
                            "title": "Notes",
                        },
                    ],
                },
                {
                    "id": "select-e9x0p1e2",
                    "type": "select",
                    "title": "Experience Level",
                    "options": [
                        {"label": "Extensive (10+ years)", "value": "e3x4t5e6"},
                        {"label": "Established (5-10 years)", "value": "e7s8t9a0"},
                        {"label": "Growing (2-5 years)", "value": "g1r2o3w4"},
                        {"label": "New (Under 2 years)", "value": "n5e6w7u8"},
                    ],
                },
                {
                    "id": "textarea-r9e0f1e2",
                    "type": "textarea",
                    "title": "Reference Check Results",
                    "placeholder": "Summary of client references and case studies",
                },
            ],
        },
        {
            "name": "Financial Analysis",
            "form_schema": [
                {
                    "id": "input-q3u4o5t6",
                    "type": "input",
                    "input": "number",
                    "title": "Total Quoted Price",
                    "required": True,
                },
                {
                    "id": "select-p7a8y9m0",
                    "type": "select",
                    "title": "Payment Terms",
                    "options": [
                        {"label": "Net 30", "value": "n1e2t3o"},
                        {"label": "Net 60", "value": "n4e5t6s"},
                        {"label": "Upfront Payment", "value": "u7p8f9r"},
                        {"label": "Monthly Recurring", "value": "m0o1n2t3"},
                        {"label": "Milestone-Based", "value": "m4i5l6e7"},
                    ],
                },
                {
                    "id": "table-c8o9s0t1",
                    "type": "table",
                    "title": "Cost Breakdown",
                    "columns": [
                        {
                            "id": "row-i2t3e4m5",
                            "type": "input",
                            "input": "text",
                            "title": "Cost Item",
                        },
                        {
                            "id": "row-a6m7o8u9",
                            "type": "input",
                            "input": "number",
                            "title": "Amount",
                        },
                        {
                            "id": "row-n0o1t2e3",
                            "type": "input",
                            "input": "text",
                            "title": "Notes",
                        },
                    ],
                },
                {
                    "id": "radio-b4u5d6g7",
                    "type": "radio",
                    "title": "Budget Assessment",
                    "options": [
                        {"label": "Well Under Budget", "value": "w8e9l0l1"},
                        {"label": "Within Budget", "value": "w2i3t4h5"},
                        {"label": "At Budget Limit", "value": "a6t7b8u9"},
                        {"label": "Over Budget", "value": "o0v1e2r3"},
                    ],
                    "required": True,
                },
            ],
        },
        {
            "name": "Risk & Compliance",
            "form_schema": [
                {
                    "id": "table-r4i5s6k7",
                    "type": "table",
                    "title": "Risk Assessment",
                    "columns": [
                        {
                            "id": "row-r8i9s0k1",
                            "type": "input",
                            "input": "text",
                            "title": "Risk Factor",
                        },
                        {
                            "id": "row-l2e3v4e5",
                            "type": "input",
                            "input": "text",
                            "title": "Impact Level",
                        },
                        {
                            "id": "row-m6i7t8i9",
                            "type": "input",
                            "input": "text",
                            "title": "Mitigation",
                        },
                    ],
                },
                {
                    "id": "checkbox-s0e1c2u3",
                    "type": "checkbox",
                    "title": "Security Review Complete",
                },
                {
                    "id": "checkbox-l4e5g6a7",
                    "type": "checkbox",
                    "title": "Legal Review Complete",
                },
                {
                    "id": "textarea-c8o9m0p1",
                    "type": "textarea",
                    "title": "Compliance Notes",
                    "placeholder": "Documentation of compliance requirements and vendor responses",
                },
            ],
        },
        {
            "name": "Final Decision",
            "form_schema": [
                {
                    "id": "radio-d2e3c4i5",
                    "type": "radio",
                    "title": "Recommendation",
                    "options": [
                        {"label": "Strongly Recommend", "value": "s6t7r8o9"},
                        {"label": "Recommend", "value": "r0e1c2o3"},
                        {"label": "Recommend with Conditions", "value": "r4e5c6w7"},
                        {"label": "Do Not Recommend", "value": "d8o9n0o1"},
                    ],
                    "required": True,
                },
                {
                    "id": "textarea-j2u3s4t5",
                    "type": "textarea",
                    "title": "Decision Rationale",
                    "placeholder": "Summary of key factors that influenced the decision",
                    "required": True,
                },
                {
                    "id": "table-n6e7x8t9",
                    "type": "table",
                    "title": "Next Steps",
                    "columns": [
                        {
                            "id": "row-a0c1t2i3",
                            "type": "input",
                            "input": "text",
                            "title": "Action Item",
                        },
                        {
                            "id": "row-o4w5n6e7",
                            "type": "input",
                            "input": "text",
                            "title": "Owner",
                        },
                        {
                            "id": "row-d8u9e0d1",
                            "type": "input",
                            "input": "date",
                            "title": "Due Date",
                        },
                    ],
                },
            ],
        },
    ],
}

ROOM_CLEANING_PROJECT_EXAMPLE = {
    "project_name": "Room Cleaning Process",
    "project_description": "Systematic approach to cleaning different rooms with consistent task organization and optional progress tracking",
    "model_tasks": [
        {"name": "Dusting & Surfaces", "form_schema": []},
        {"name": "Floor Cleaning", "form_schema": []},
        {
            "name": "Final Check",
            "form_schema": [
                {
                    "id": "checkbox-c9l0e1a2",
                    "type": "checkbox",
                    "title": "All Items Returned to Place",
                },
                {
                    "id": "checkbox-t3r4a5s6",
                    "type": "checkbox",
                    "title": "Trash Emptied",
                },
                {
                    "id": "input-t7i8m9e0",
                    "type": "input",
                    "input": "number",
                    "title": "Total Time (minutes)",
                },
            ],
        },
    ],
}

MONTHLY_SCHEDULING_EXAMPLES = [
    {
        "request": "first Monday",
        "example": {
            "type": "ordinal_weekday",
            "ordinal": 1,
            "weekday": 0,
            "day": None,
            "text": "first Monday of the month",
        },
    },
    {
        "request": "15th",
        "example": {
            "type": "specific_day",
            "day": 15,
            "ordinal": None,
            "weekday": None,
            "text": "15th of the month",
        },
    },
    {
        "request": "last day of the month",
        "example": {
            "type": "last_day",
            "day": None,
            "ordinal": None,
            "weekday": None,
            "text": "last day of the month",
        },
    },
    {
        "request": "third Friday",
        "example": {
            "type": "ordinal_weekday",
            "ordinal": 3,
            "weekday": 4,
            "day": None,
            "text": "third Friday of the month",
        },
    },
    {
        "request": "last Tuesday",
        "example": {
            "type": "ordinal_weekday",
            "ordinal": -1,
            "weekday": 1,
            "day": None,
            "text": "last Tuesday of the month",
        },
    },
]

YEARLY_SCHEDULING_EXAMPLES = [
    {
        "request": "December 25th",
        "example": {
            "month": 12,
            "type": "specific_day",
            "day": 25,
            "ordinal": None,
            "weekday": None,
            "text": "annually on December 25th",
        },
    },
    {
        "request": "third Thursday in November",
        "example": {
            "month": 11,
            "type": "ordinal_weekday",
            "ordinal": 3,
            "weekday": 3,
            "day": None,
            "text": "annually on the third Thursday in November",
        },
    },
    {
        "request": "last day of June",
        "example": {
            "month": 6,
            "type": "last_day",
            "day": None,
            "ordinal": None,
            "weekday": None,
            "text": "annually on the last day of June",
        },
    },
    {
        "request": "first Monday in September",
        "example": {
            "month": 9,
            "type": "ordinal_weekday",
            "ordinal": 1,
            "weekday": 0,
            "day": None,
            "text": "annually on the first Monday in September",
        },
    },
    {
        "request": "last Friday in December",
        "example": {
            "month": 12,
            "type": "ordinal_weekday",
            "ordinal": -1,
            "weekday": 4,
            "day": None,
            "text": "annually on the last Friday in December",
        },
    },
]

PERIODIC_SCHEDULING_EXAMPLES = [
    {
        "request": "every 3 days",
        "example": {"unit": "day", "interval": 3, "text": "every 3 days"},
    },
    {
        "request": "every 2 weeks",
        "example": {"unit": "week", "interval": 2, "text": "every 2 weeks"},
    },
    {
        "request": "monthly",
        "example": {"unit": "month", "interval": 1, "text": "every month"},
    },
    {
        "request": "every other week",
        "example": {"unit": "week", "interval": 2, "text": "every other week"},
    },
    {
        "request": "every 6 months",
        "example": {"unit": "month", "interval": 6, "text": "every 6 months"},
    },
    {
        "request": "annually",
        "example": {"unit": "year", "interval": 1, "text": "every year"},
    },
]
