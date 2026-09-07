# -*- coding: utf-8 -*-
"""The Foundry tool spec must be valid before anyone pastes it into Foundry.

This file exists because a hand-edit put `"required": []` into the
render_report request body. An empty `required` array is invalid JSON Schema -
it needs at least one entry - and Foundry rejected the whole spec with
`'$ref' is a required property`, an error that points at a keyword the file
never used. The tool went dead and the message sent us looking in the wrong
place. A spec is code; it gets a test.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "foundry" / "openapi-servicing.json"

FAILURES: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  PASS  {label}{(': ' + detail) if detail else ''}")
    else:
        FAILURES.append(label)
        print(f"  FAIL  {label}: {detail}")


spec = json.loads(SPEC.read_text())

print("== the spec validates as OpenAPI 3.0.3 ==")
try:
    from openapi_spec_validator import validate

    validate(spec)
    check("openapi_spec_validator accepts it", True)
except ImportError:
    print("  SKIP  openapi_spec_validator not installed; running structural checks only")
except Exception as exc:  # noqa: BLE001
    check("openapi_spec_validator accepts it", False, str(exc)[:400])

print("\n== no empty `required` arrays anywhere ==")
empty: list[str] = []


def walk(node, path="root"):
    if isinstance(node, dict):
        req = node.get("required")
        if isinstance(req, list) and not req:
            empty.append(path)
        for k, v in node.items():
            walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            walk(v, f"{path}[{i}]")


walk(spec)
check("no `required: []`", not empty, ", ".join(empty))

print("\n== the three operations the prompt calls still exist, by name ==")
ops = {
    op["operationId"]
    for path in spec["paths"].values()
    for op in path.values()
    if isinstance(op, dict) and "operationId" in op
}
for name in ("extract_and_normalize", "compute_summary", "render_report"):
    check(f"{name} is declared", name in ops, ", ".join(sorted(ops)))

print("\n== the id-based contract the prompt depends on is advertised ==")
ex = spec["paths"]["/extract_and_normalize"]["post"]["responses"]["200"]
ex_props = ex["content"]["application/json"]["schema"].get("properties", {})
check("extract advertises batch_id", "batch_id" in ex_props, ", ".join(sorted(ex_props)))
check("extract advertises classification_worklist", "classification_worklist" in ex_props)
check("extract advertises transaction_count", "transaction_count" in ex_props)

cs_props = (
    spec["paths"]["/compute_summary"]["post"]["requestBody"]["content"]["application/json"]
    ["schema"]["properties"]
)
check("compute accepts batch_id", "batch_id" in cs_props, ", ".join(sorted(cs_props)))
check("compute still accepts canonical for scripts", "canonical" in cs_props)

cs_resp = (
    spec["paths"]["/compute_summary"]["post"]["responses"]["200"]["content"]
    ["application/json"]["schema"].get("properties", {})
)
check("compute advertises summary_id", "summary_id" in cs_resp, ", ".join(sorted(cs_resp)))

rr_props = (
    spec["paths"]["/render_report"]["post"]["requestBody"]["content"]["application/json"]
    ["schema"]["properties"]
)
check("render accepts summary_id", "summary_id" in rr_props, ", ".join(sorted(rr_props)))
check("render still accepts summary for scripts", "summary" in rr_props)

print("\n== the server URL is the live Function App ==")
url = spec["servers"][0]["url"]
check("https", url.startswith("https://"), url)
check("no trailing slash", not url.endswith("/"), url)

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}): " + ", ".join(FAILURES))
    raise SystemExit(1)
print("Spec is valid and matches the contract the prompt assumes.")
