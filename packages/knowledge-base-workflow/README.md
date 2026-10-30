# tools-knowledge-base-workflow

The `workflow` memory kind for the Knowledge Base: a named procedure the user
follows, registered as `workflow` in the `tools_knowledge_base.memory_kinds`
entry-point group. Installing the package is the whole activation step.

A payload is a `name`, an optional `description` and
`steps`, an ordered list of strings that keeps its order through storage and
search. The natural key is `name`: re-storing it upserts one item with the new
description and steps, while an edit that renames the workflow moves the item to
a new id. The embedded text is `name: description` (just `name` when the
description is blank) followed by the steps, one per line, capped as a whole at
`item_limits.max_chars.workflow` characters (500 by default).

An update replaces the whole payload, so `update-workflow` without
`--description` clears the stored description.

On the CLI `--steps` is repeatable; each occurrence is one step, in order:

```
knowledge-base-cli store-workflow --name "morning routine" --steps "coffee" --steps "email"
```
