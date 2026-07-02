# tools/rag/schema_composer.py
"""Schema composition utilities — $ref resolution, allOf merging, inheritance.

Supports three patterns:
  1. $ref: local file reference   {"$ref": "base_input.json#/definitions/Foo"}
  2. allOf: merge multiple schemas {"allOf": [{"$ref": "..."}, {"properties": {...}}]}
  3. x-extends: convenience key   {"x-extends": "base_input.json", "properties": {...}}

Usage:
    from tools.rag.schema_composer import SchemaComposer
    composer = SchemaComposer(base_dir="config/schemas")
    resolved = composer.resolve(schema_dict)
    merged   = composer.compose([schema_a, schema_b])
"""

from __future__ import annotations

import copy
import json
import os
from typing import Any


class SchemaComposer:
    """Resolve $ref / allOf / x-extends in JSON Schemas.

    Resolution is purely local (file references only, no HTTP).
    Circular references are detected and raise ValueError.
    """

    def __init__(self, base_dir: str = "config/schemas") -> None:
        self.base_dir = base_dir
        self._cache: dict[str, dict] = {}

    # ------------------------------------------------------------------ public

    def resolve(self, schema: dict[str, Any], _stack: frozenset[str] | None = None) -> dict[str, Any]:
        """Return a fully-resolved copy of *schema* with all $ref expanded."""
        _stack = _stack or frozenset()
        schema = copy.deepcopy(schema)

        # 1. x-extends (convenience shorthand)
        if "x-extends" in schema:
            base_name = schema.pop("x-extends")
            base = self._load_file(base_name, _stack)
            schema = self._merge(base, schema)

        # 2. $ref at top level
        if "$ref" in schema:
            ref = schema.pop("$ref")
            ref_schema = self._resolve_ref(ref, _stack)
            schema = self._merge(ref_schema, schema)

        # 3. allOf
        if "allOf" in schema:
            merged: dict[str, Any] = {}
            for sub in schema.pop("allOf"):
                sub_resolved = self.resolve(sub, _stack)
                merged = self._merge(merged, sub_resolved)
            schema = self._merge(merged, schema)

        # 4. Recurse into properties
        for key, value in schema.get("properties", {}).items():
            if isinstance(value, dict):
                schema["properties"][key] = self.resolve(value, _stack)

        return schema

    def compose(self, schemas: list[dict[str, Any]]) -> dict[str, Any]:
        """Merge a list of schemas left-to-right (later wins on conflicts)."""
        result: dict[str, Any] = {}
        for schema in schemas:
            result = self._merge(result, self.resolve(schema))
        return result

    def load_and_resolve(self, filename: str) -> dict[str, Any]:
        """Load a schema file by name and fully resolve it."""
        raw = self._load_file(filename, frozenset())
        return self.resolve(raw, frozenset({filename}))

    # ----------------------------------------------------------------- private

    def _load_file(self, filename: str, stack: frozenset[str]) -> dict[str, Any]:
        # Strip anchor (#/...)
        parts = filename.split("#", 1)
        fname = parts[0]
        anchor = parts[1] if len(parts) > 1 else None

        if fname in stack:
            raise ValueError(f"Circular schema reference: {fname} in {stack}")

        if fname not in self._cache:
            path = os.path.join(self.base_dir, fname)
            if not os.path.isabs(fname) and not os.path.exists(path):
                raise FileNotFoundError(f"Schema file not found: {path}")
            with open(path, encoding="utf-8") as f:
                self._cache[fname] = json.load(f)

        schema = copy.deepcopy(self._cache[fname])

        if anchor:
            # Navigate JSON Pointer (e.g. /definitions/Foo)
            for segment in anchor.strip("/").split("/"):
                if isinstance(schema, dict) and segment in schema:
                    schema = schema[segment]
                else:
                    raise KeyError(f"JSON Pointer {anchor!r} not found in {fname}")

        return self.resolve(schema, stack | {fname})

    def _resolve_ref(self, ref: str, stack: frozenset[str]) -> dict[str, Any]:
        return self._load_file(ref, stack)

    @staticmethod
    def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """Deep-merge *override* into *base*; override wins on scalar conflicts."""
        result = copy.deepcopy(base)
        for key, val in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(val, dict):
                result[key] = SchemaComposer._merge(result[key], val)
            elif key in result and isinstance(result[key], list) and isinstance(val, list):
                # For 'required' and similar arrays: union
                result[key] = list(dict.fromkeys(result[key] + val))
            else:
                result[key] = copy.deepcopy(val)
        return result
