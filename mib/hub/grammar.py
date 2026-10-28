"""GBNF for single-line JSON from a small JSON-schema subset.

llama-server's built-in json_schema conversion allows free whitespace and LFM3 pretty-prints, so a large
share of the generated tokens becomes indentation, at ~11 tok/s on a Pi 5. This grammar emits one line with
Python-style separators (", " and ": "): fully minified JSON made the model start values with a stray ":".
Keys come in declared order and every key is required.

Supported: object (properties), array (items, minItems, maxItems), string (enum, minLength, maxLength),
integer (enum, minimum..maximum), number, boolean.
"""

from __future__ import annotations

import json
import re

_CHAR_RULE = r'[^"\\\x00-\x1f] | "\\" ["\\/bfnrt]'


def _lit(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


class _Builder:
    def __init__(self) -> None:
        self.rules: dict[str, str] = {}

    def _name(self, hint: str) -> str:
        base = re.sub(r"[^a-zA-Z0-9]+", "-", hint).strip("-").lower() or "r"
        name, i = base, 2
        while name in self.rules:
            name, i = f"{base}-{i}", i + 1
        return name

    def add(self, hint: str, body: str) -> str:
        name = self._name(hint)
        self.rules[name] = body
        return name

    def visit(self, schema: dict, hint: str) -> str:
        if "enum" in schema:
            return self.add(hint, " | ".join(_lit(json.dumps(v, ensure_ascii=False)) for v in schema["enum"]))
        kind = schema.get("type")
        if kind == "object":
            parts = ['"{"']
            for i, (key, sub) in enumerate(schema.get("properties", {}).items()):
                parts.append(_lit((", " if i else "") + json.dumps(key) + ": "))
                parts.append(self.visit(sub, f"{hint}-{key}"))
            parts.append('"}"')
            return self.add(hint, " ".join(parts))
        if kind == "array":
            item = self.visit(schema["items"], f"{hint}-item")
            lo, hi = int(schema.get("minItems", 0)), schema.get("maxItems")
            if hi is not None and int(hi) == 0:
                return self.add(hint, '"[]"')
            tail_hi = "" if hi is None else str(int(hi) - 1)
            if lo == 0:
                body = f'"[" ( {item} ( ", " {item} ){{0,{tail_hi}}} )? "]"'
            else:
                body = f'"[" {item} ( ", " {item} ){{{lo - 1},{tail_hi}}} "]"'
            return self.add(hint, body)
        if kind == "string":
            lo, hi = int(schema.get("minLength", 0)), schema.get("maxLength")
            rep = f"{{{lo},{'' if hi is None else int(hi)}}}"
            return self.add(hint, f'"\\"" char{rep} "\\""')
        if kind == "integer":
            lo, hi = schema.get("minimum"), schema.get("maximum")
            if lo is not None and hi is not None and 0 <= hi - lo <= 200:
                return self.add(hint, " | ".join(_lit(str(v)) for v in range(int(lo), int(hi) + 1)))
            return self.add(hint, '"-"? [0-9]{1,12}')
        if kind == "number":
            return self.add(hint, '"-"? [0-9]{1,12} ( "." [0-9]{1,6} )?')
        if kind == "boolean":
            return self.add(hint, '"true" | "false"')
        raise ValueError(f"unsupported schema at {hint}: {schema}")


def compact_json_grammar(schema: dict) -> str:
    builder = _Builder()
    builder.rules["char"] = _CHAR_RULE
    top = builder.visit(schema, "value")
    lines = [f"root ::= {top}"] + [f"{name} ::= {body}" for name, body in builder.rules.items()]
    return "\n".join(lines) + "\n"
