# tools-knowledge-base-knowledge

The `knowledge` memory kind for the Knowledge Base: atomic facts about the user,
registered as `knowledge` in the `tools_knowledge_base.memory_kinds` entry-point
group. Installing the package is the whole activation step.

A payload is a `category` (`fact | preference | constraint | goal`) and its
`content`. The content is both the natural key and the embedded text, so
re-storing the same text upserts one item, and an edit that rewords it moves the
item to a new id. The content is capped at `item_limits.max_chars.knowledge`
characters (500 by default).

```
knowledge-base-cli store-knowledge --category fact --content "the sky is blue"
```
