---
name: pydantic-scalar-or-list-field-pitfall
description: Field(ge=, le=) on a bare `int | list[int]` union annotation crashes at validation time — must wrap the int branch in Annotated
metadata:
  type: project
---

Discovered while adding `chunking.chunk_size: int | list[int]` (US-03, hierarchical chunking
supports per-level size lists) to `config/settings.py`.

`chunk_size: int | list[int] = Field(default=1024, ge=64, le=8192)` raises
`TypeError: Unable to apply constraint 'ge' to supplied value [...]` the moment a list value is
validated — pydantic v2 applies top-level `Field(ge=/le=)` constraints to every branch of a
Union, not just the numeric one.

**Fix pattern**: wrap only the constrained branch —
`chunk_size: Annotated[int, Field(ge=64, le=8192)] | list[int] = Field(default=1024)`, then add
a `@field_validator` for the list branch's own rules (min length, ordering, etc.). The plain
`field.metadata` on a `FieldInfo` won't show these nested constraints either — reading them back
(e.g. for a `/settings/schema` endpoint) requires digging into `get_args()` of the Annotated
union member; see `_int_range_from_union_annotation` in `config/settings.py` for the pattern.

**How to apply**: Any future "this field is normally a scalar but needs a list variant for one
mode" field in Settings should use this Annotated-per-branch shape, not a bare `Field(ge=,le=)`
next to a Union annotation.
