---
name: judge-skill
description: Evaluate a reviewer report against hidden reference defects and write one structured judgment.
compatibility: Requires bash
---

# Judge Skill

Read the reviewer report and the hidden reference label supplied in the task. Treat the label as the reference for expected defects, but inspect the diff and repository when needed to determine whether a reviewer finding is supported.

Write judgment.json as one JSON object. See [the template](assets/template.json) for the complete shape.

Include exactly one label assessment for every label defect. Include exactly one reviewer assessment for every reviewer finding. Use empty arrays when there are no labels or no reviewer findings. A matched label may reference one or more reviewer findings. A supported reviewer finding may reference one or more label indexes.

Do not invent defects, IDs, label indexes or reviewer findings. Do not write report.json or report.md. Write only judgment.json to the requested path.
