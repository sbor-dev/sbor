---
name: judge-skill
description: Evaluate a reviewer report against hidden reference defects and write one structured judgment.
compatibility: Requires bash
---

# Judge Skill

Read the reviewer report and the hidden reference label supplied in the task. Treat the label as the reference for expected defects, but inspect the diff and repository when needed to determine whether a reviewer finding is supported.

Write judgment.json as one JSON object. See [the template](assets/template.json) for the complete shape.

Include exactly one label assessment for every label defect. Include exactly one reviewer assessment for every reviewer finding. Use empty arrays when there are no labels or no reviewer findings. A matched label may reference one or more reviewer findings. A supported reviewer finding may reference one or more label indexes.

## Verdict semantics

Evaluate reviewer findings independently from the reference labels:

- A finding is `supported` when it describes a real defect introduced by the canonical diff and its claims are supported by the diff and repository.
- A finding is `unsupported` when it is false, speculative, or outside the canonical diff.
- A finding does not become `unsupported` merely because no reference label describes it. A supported finding may have an empty `label_indexes` array because the labels can be incomplete.
- Every hunk in the canonical diff is part of the reviewed change, regardless of the merge request title, commit subject, surrounding history, or which defect appears intentionally injected.

Assess labels separately. A label is `matched` when at least one supported reviewer finding identifies that defect and `missed` otherwise. An unsupported finding must have an empty `label_indexes` array and must not be referenced by a label assessment. Keep references symmetric: each finding ID listed by a label assessment must list that label index in its reviewer assessment, and vice versa.

Do not invent defects, IDs, label indexes or reviewer findings. Do not write report.json or report.md. Write only judgment.json to the requested path.
