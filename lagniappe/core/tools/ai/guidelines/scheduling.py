"""
Scheduling guidelines for monthly, yearly, and periodic patterns.
"""

MONTHLY_SCHEDULING_PROMPT_RULES = """
### Monthly Scheduling

- Identify the type of scheduling pattern based on the user input
- Extract relevant details based on the pattern type

#### Pattern Types:
1. "specific_day" - exact day number (e.g., "15th", "1st", "31st")
2. "ordinal_weekday" - ordinal + weekday (e.g., "first Monday", "third Friday", "last Tuesday")
3. "last_day" - last day of month (e.g., "last day", "end of month")
4. "first_day" - first day of month (e.g., "first day", "beginning of month") (preferred over specific_day type with day=1)

#### Field Specifications:
- "type": one of the pattern types above
- "day": number 1-31 (only for specific_day type)
- "ordinal": number 1-4 for first/second/third/fourth, or -1 for last (only for ordinal_weekday type)
- "weekday": number 0-6 where 0=Monday, 1=Tuesday, 2=Wednesday, 3=Thursday, 4=Friday, 5=Saturday, 6=Sunday (only for ordinal_weekday type)
"""

MONTHLY_SCHEDULING_OUTPUT_REQUIREMENTS = """
### Monthly Scheduling Output Requirements

**Return only a valid JSON object with all of the following properties:**
  - `type`: one of the pattern types above
  - `day`: number 1-31 (only for specific_day type)
  - `ordinal`: number 1-4 for first/second/third/fourth, or -1 for last (only for ordinal_weekday type)
  - `weekday`: number 0-6 where 0=Monday, 1=Tuesday, 2=Wednesday, 3=Thursday, 4=Friday, 5=Saturday, 6=Sunday (only for ordinal_weekday type)
  - `text`: text describing the schedule, as short and concise as possible, suitable for a user to understand. i.e. 'first Monday of the month', 'every 3rd Tuesday of the month'

**Include all properties. If not applicable, set to `null`.**
**If the request is unclear, make your best guess. If the request is clearly impossible, set all properties to `null`.**
"""

YEARLY_SCHEDULING_PROMPT_RULES = """
### Yearly Scheduling

- Extract month (1-12) and scheduling pattern
- Identify the type of scheduling pattern within that month

#### Pattern Types:
1. "specific_day" - exact day number (e.g., "December 25th", "January 1st")
2. "ordinal_weekday" - ordinal + weekday (e.g., "first Monday in March", "third Thursday in November")
3. "last_day" - last day of month (e.g., "last day of June")
4. "first_day" - first day of month (e.g., "first day of January") (preferred over specific_day type with day=1)

#### Field Specifications:
- "month": number 1-12 (January=1, February=2, etc.)
- "type": one of the pattern types above
- "day": number 1-31 (only for specific_day type)
- "ordinal": number 1-4 for first/second/third/fourth, or -1 for last (only for ordinal_weekday type)
- "weekday": number 0-6 where 0=Monday, 1=Tuesday, 2=Wednesday, 3=Thursday, 4=Friday, 5=Saturday, 6=Sunday (only for ordinal_weekday type)
"""

YEARLY_SCHEDULING_OUTPUT_REQUIREMENTS = """
### Yearly Scheduling Output Requirements

**Return only a valid JSON object with all of the following properties:**
- `month`: number 1-12 (January=1, February=2, etc.)
- `type`: one of the pattern types above
- `day`: number 1-31 (only for specific_day type)
- `ordinal`: number 1-4 for first/second/third/fourth, or -1 for last (only for ordinal_weekday type)
- `weekday`: number 0-6 where 0=Monday, 1=Tuesday, 2=Wednesday, 3=Thursday, 4=Friday, 5=Saturday, 6=Sunday (only for ordinal_weekday type)
- `text`: text describing the schedule, as short and concise as possible, suitable for a user to understand. i.e. 'last day of the year', 'every 3rd Tuesday in January'

**Include all properties. If not applicable, set to `null`.**
**If the request is unclear, make your best guess. If the request is clearly impossible, set all properties to `null`.**
"""

PERIODIC_SCHEDULING_PROMPT_RULES = """
### Periodic Scheduling

- Extract the unit (day, week, month, year) and interval (number) from the text
- The interval should be a positive integer
- The unit should be one of: day, week, month, year

#### Examples of Patterns to Recognize
- "every 3 days" → unit: "day", interval: 3
- "every 2 weeks" → unit: "week", interval: 2  
- "every month" → unit: "month", interval: 1
- "every other week" → unit: "week", interval: 2
- "every 6 months" → unit: "month", interval: 6
- "annually" or "every year" → unit: "year", interval: 1
- "daily" → unit: "day", interval: 1
- "weekly" → unit: "week", interval: 1
- "biweekly" → unit: "week", interval: 2
- "quarterly" → unit: "month", interval: 3

#### Field Specifications
- "unit": one of "day", "week", "month", "year"  
- "interval": positive integer (1, 2, 3, etc.)
"""

PERIODIC_SCHEDULING_OUTPUT_REQUIREMENTS = """
### Periodic Scheduling Output Requirements

**Return only a valid JSON object with all of the following properties:**
  - `unit`: one of "day", "week", "month", "year"  
  - `interval`: positive integer (1, 2, 3, etc.)
  - `text`: text describing the schedule, as short and concise as possible, suitable for a user to understand. i.e. 'every 3 days', 'every 2 weeks', 'every month', 'every other week', 'every 6 months', 'every year'
  
**Include all properties. If not applicable, set to `null`.**
**If the request is unclear, make your best guess. If the request is clearly impossible, set all properties to `null`.**
"""


REPORT_TASK_SCHEDULING_GUIDELINES = """
### Report Task Scheduling

`create_task.data.schedule` creates reviewed repeating work. Keep a one-time
reminder in `due_date` without a schedule. When a schedule is requested, return
one of these canonical shapes and also include a concrete `due_date` when the
user supplied or implied a starting date:

- Repeat after completion: `{"kind": "recurring", "interval": 2, "unit": "week"}`.
- Daily calendar schedule: `{"kind": "scheduled", "mode": "daily"}`.
- Weekly calendar schedule: `{"kind": "scheduled", "mode": "weekly", "days": [0, 2]}`,
  where Monday is 0 and Sunday is 6.
- Monthly calendar pattern: `{"kind": "scheduled", "mode": "monthly",
  "pattern_type": "specific_day"|"ordinal_weekday"|"first_day"|"last_day",
  ...pattern fields..., "description": "...", "user_prompt": "..."}`.
- Yearly calendar pattern: the monthly shape with `mode: "yearly"` and `month`
  from 1 through 12.
- A freeform fixed interval: `{"kind": "periodic", "interval": 3,
  "unit": "month", "description": "every quarter", "user_prompt": "quarterly"}`.

Units are `day`, `week`, `month`, or `year`; intervals are positive integers.
For `specific_day`, include `day` from 1 through 31. For `ordinal_weekday`,
include `ordinal` as 1, 2, 3, 4, or -1 for last, plus `weekday` from 0 through 6.
Use the user's wording for `user_prompt` and a concise readable rendering for
`description`. Do not add a schedule to a completed occurrence, and do not
invent recurrence when the request describes only one deadline or reminder.
"""
