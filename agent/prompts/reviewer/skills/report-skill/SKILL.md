---
name: report-skill
description: Write report with found code defects. Use when you have finished code audit.
compatibility: Requires bash
---

# Report Skill

- By finishing your code audit session you have to write a report with all found defects. Report contains 2 files:
  1. `report.md` - contains all found defects in markdown format (human-readable)
  2. `report.json` - contains all found defects in JSON format (machine-readable)

- By writing a report you have to assign a hash id to each found defect. Hash id is a unique identifier of the defect, but it HAS to be SAME for both `report.md` and `report.json`. You can use any hash function to generate hash id, but it has to be consistent.

## JSON report

See [the template](assets/template.json) for template.

- Write down a detailed explanation of each found defect in the `report.json` file. But DO NOT include unnecessary code snippets or terminal outputs in the `report.json` file. Include them ONLY if they are necessary to understand the defect. If you include code snippets or terminal outputs, make sure they are cropped and relevant to the defect. 
- This file will be used by other agents and tools to analyze the found defects, so it is important to keep it clean and structured.
- `category` must be `Functional` or `Evolvability`.
- `file` must be a path relative to the repository root.
- `start_line` and `end_line` must refer to the reviewed repository state. Both must be positive integers, and `end_line` must not be less than `start_line`.

## Markdown report

See [the template](assets/template.md) for template.

- Write down a detailed explanation of each found defect in the `report.md` file. Include code snippets or terminal outputs, e.t.c. This file will be used by humans to understand the found defects, so it is important to keep it readable and simple to understand. Use markdown formatting to make it more readable.
