"""
Project generation guidelines.
"""

PROJECT_GENERATION_GUIDELINES = """
### Project Guidelines

#### What is a Project?

- A project is an organizational tool that groups related tasks under a common theme or process.
- Projects may represent a multi-step workflow with sequential phases, OR a collection of related but independent types of work.
- Model tasks define the distinct categories or phases of work within a project.
- Model tasks can optionally have forms attached to them for consistent data collection.
- Forms attached to model tasks should collect data that is specific to that type of work.
- Forms attached to model tasks should describe the task (e.g., "Literature Review", "Vendor Evaluation", "Holiday Cards")
- Projects should be for recurring or ongoing concerns, not one-time events

#### Model Task Design Guidelines

- Each model task should represent a DISTINCT category or type of work.
- Avoid being too granular (don't create separate model tasks for minor variations).
- Aim for 3-7 model tasks per project - enough to organize work, not so many as to be overwhelming.
- For sequential projects, order model tasks in the typical sequence someone would follow.
- For thematic projects, group model tasks by logical category.
- Model task names should be clear, descriptive, and describe the work being done.
- Examples: "Literature Review", "Vendor Evaluation", "Holiday Cards", "Wedding Gifts".
- Avoid vague names like "Step 1" or "Phase A".

#### Model Task Form Design Strategy

- Not every model task needs a form - only attach forms when consistent data collection adds value.
- Focus forms on information that will help track progress, make decisions, or filter tasks.
- Consider what questions someone would ask when reviewing this type of work.

#### Example Project Patterns

**Sequential Projects (multi-step workflows):**

*Research & Analysis:*
- Model Tasks: "Literature Review" → "Data Collection" → "Analysis" → "Report Writing"
- Focus: Source evaluation, methodology tracking, findings documentation

*Vendor/Supplier Evaluation:*
- Model Tasks: "Initial Research" → "Capability Assessment" → "Financial Analysis" → "Risk Review" → "Final Decision"  
- Focus: Requirements matching, cost analysis, risk mitigation

*Product Development:*
- Model Tasks: "Concept Design" → "Prototyping" → "Testing" → "Production Planning"
- Focus: Design specifications, test results, manufacturing requirements

**Thematic Projects (related but independent tasks):**

*Relationship Management:*
- Model Tasks: "Holiday Cards", "Wedding Gifts", "Follow-Ups", "Catch-Ups", "Thank You Notes"
- Focus: Tracking people, occasions, and actions across different social obligations

*Home Maintenance:*
- Model Tasks: "Seasonal Checks", "Appliance Servicing", "Yard Work", "Deep Cleaning"
- Focus: Scheduling, tracking what was done, noting issues

*Personal Finance:*
- Model Tasks: "Bill Payments", "Investment Reviews", "Tax Preparation", "Insurance Renewals"
- Focus: Deadlines, amounts, account details, status tracking
"""

PROJECT_OUTPUT_REQUIREMENTS = """
### Project Output Requirements

- Return only a valid JSON object with the following properties:
  - `project_name`: String
  - `project_description`: String
  - `model_tasks`: Array of objects, each with the following properties:
    - `name`: String
    - `form_schema`: Array of form elements following the form generation rules above
"""

PROJECT_COMPLEXITY_GUIDELINES = """
#### Project Complexity Guidelines

Projects can range from simple task organization to complex workflows:

**Simple Projects:**
- 3-4 model tasks with minimal or no forms
- Focus on task organization and categorization
- Example: "Room Cleaning" with tasks like "Dusting", "Vacuuming", "Mopping", "Organizing"
- Forms only added when data collection provides clear value

**Medium Projects:**
- 4-6 model tasks with selective form usage
- Mix of organizational and data-collection categories
- Some tasks track progress, others collect specific information

**Complex Projects:**
- 5-7 model tasks with comprehensive forms
- Detailed data collection for decision-making and analysis
- Examples: Research projects, vendor evaluations, relationship management
"""
