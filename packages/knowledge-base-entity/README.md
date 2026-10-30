# tools-knowledge-base-entity

The `entity` memory kind for the Knowledge Base: a named thing the user deals
with, registered as `entity` in the `tools_knowledge_base.memory_kinds`
entry-point group. Installing the package is the whole activation step.

A payload is a `name`, a `type` (`person | system | project | concept |
organization | tool`) and a `description`. The natural key is the pair
`(name, type)`: re-storing it upserts one item with the new description, while
the same name under another type is a separate item, and an edit that changes
the name or type moves the item to a new id. The embedded text is
`name: description`, capped at `item_limits.max_chars.entity` characters (500 by
default).

```
knowledge-base-cli store-entity --name Alice --type person --description "the user"
```
