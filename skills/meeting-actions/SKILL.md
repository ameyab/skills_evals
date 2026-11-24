---
name: meeting-actions
description: Convert meeting notes into action items with owners and dates, preserving uncertainty.
---

# Meeting actions

Extract explicit commitments and keep discussion separate from decisions.
- For each action, include the action, owner, and due date only when stated.
- Preserve a named team or department as the owner; an owner does not need to be an individual person.
- Mark missing owner or date as “not specified”; never infer them from context.
- Keep actions separate from suggestions and undecided topics; put the latter in a distinct discussion or open-questions section.
- Preserve names, dates, and deliverables exactly.
- Keep the result concise and scannable. Return only the requested artifact.

Before returning, check that every stated owner and date is retained and that no discussion item became an action.
