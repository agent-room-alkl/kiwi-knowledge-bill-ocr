# -*- coding: utf-8 -*-
"""HTTP wrappers for Foundry OpenAPI tools."""

from __future__ import annotations

import base64
import json
import sys
from datetime import date
from pathlib import Path

import azure.functions as func

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))

from compute_summary import compute_summary  # noqa: E402
from extract_normalize import (  # noqa: E402
    BatchNotFound,
    classification_worklist as _classification_worklist,
    ExtractionError,
    extract_and_normalize as _extract_and_normalize,
    load_batch as _load_batch,
    merge_classifications as _merge_classifications,
    publish_report as _publish_report,
    store_batch as _store_batch,
)
from render_html import build_report_artifacts  # noqa: E402
from render_report import build_workbook  # noqa: E402

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


def _json(req: func.HttpRequest) -> dict:
    body = req.get_json()
    if not isinstance(body, dict):
        raise ValueError("JSON object required")
    return body


def _ok(payload: dict, status=200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(payload),
        status_code=status,
        mimetype="application/json",
    )


def _err(message: str, status=400) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"error": message}),
        status_code=status,
        mimetype="application/json",
    )


@app.route(route="extract_and_normalize", methods=["POST"])
def extract_and_normalize(req: func.HttpRequest) -> func.HttpResponse:
    """Document Intelligence prebuilt-layout -> canonical transaction rows.

    Accepts `file_urls` (what an agent can supply) or `files` with
    `content_base64` (what a script holding the bytes can supply).
    """
    try:
        body = _json(req)
    except ValueError as exc:
        return _err(str(exc))

    files = body.get("files") or []
    file_urls = body.get("file_urls") or []
    binder = body.get("binder") or None
    prefix = body.get("prefix") or None
    assessment_date = body.get("assessment_date") or date.today().isoformat()

    if not files and not file_urls and not binder:
        return _err("supply binder, file_urls or files; extraction has nothing to read", 400)

    try:
        batch = _extract_and_normalize(
            files, assessment_date, file_urls=file_urls, binder=binder, prefix=prefix
        )
    except ExtractionError as exc:
        # Missing credentials or an unreadable binder: say so, return no rows.
        return _ok(
            {
                "assessment_date": assessment_date,
                "applicant": {
                    "Full Name(s)": "Not provided in binder",
                    "Age(s)": "Not provided in binder",
                    "Dependants": "Not provided in binder",
                    "Address and living situation": "Not provided in binder",
                },
                "accounts": [],
                "document_index": [],
                "transaction_count": 0,
                "nonzero_amount_count": 0,
                "transactions_omitted": True,
                "status": "extract_failed",
                "message": str(exc),
                "file_count": len(files) + len(file_urls),
            },
            status=200,
        )

    # One entry per merchant needing judgement, instead of one per row. This is
    # what the caller classifies; the rows stay here.
    batch["classification_worklist"] = _classification_worklist(batch)

    # Store the batch server-side so the next tool call can name it instead of
    # carrying it. A failure to store is not fatal - the full canonical is still
    # in this response for script callers - but it must be visible, because a
    # silently missing batch_id sends the agent back to the 290 KB round trip
    # that truncates.
    try:
        batch["batch_id"] = _store_batch(batch)
    except Exception as exc:  # noqa: BLE001
        batch["batch_id"] = None
        batch["batch_store_error"] = str(exc)

    txns = batch.get("transactions") or []
    batch["status"] = "ok" if txns else "extract_failed"
    batch["file_count"] = len(batch["accounts"]) or (len(files) + len(file_urls))
    batch["transaction_count"] = len(txns)
    batch["nonzero_amount_count"] = sum(
        1 for t in txns if float(t.get("amount") or 0) != 0
    )
    if not txns:
        batch["message"] = (
            "no transactions could be read from the supplied files; "
            + "; ".join(batch.get("errors") or ["no reason recorded"])
        )
    # Agents blow the gpt-5 output cap if we also hand back 611 rows. The
    # rows stay in blob storage under batch_id. Scripts that need the array
    # pass include_transactions=true.
    if not body.get("include_transactions"):
        batch.pop("transactions", None)
        batch["transactions_omitted"] = True
    return _ok(batch)


def _as_classification_payload(raw):
    """Foundry sometimes posts the array, not the wrapper object.

    OpenAPI documents `{assessment_date, classifications:[...]}`. The Chat
    agent still sends a bare list. Left as-is, the next `.get` raises
    `'list' object has no attribute 'get'` and the underwriter sees a 400
    instead of a report.
    """
    if raw is None:
        return {}
    if isinstance(raw, list):
        return {"classifications": raw}
    if isinstance(raw, dict):
        return raw
    raise ValueError(
        "classifications must be an object {assessment_date, classifications:[...]} "
        f"or a list of entries, not {type(raw).__name__}"
    )


def _check_not_truncated(canonical: dict, classifications) -> None:
    """Reject a payload that arrived cut in half, and say so in those words.

    A truncated array shows up as a trailing `null` or a row with no
    transaction_id. Left alone it surfaces as `'NoneType' object has no
    attribute get` - an error that sends whoever reads it looking for a bug in
    the calculation instead of at the size of what they sent.
    """
    rows = canonical.get("transactions")
    if isinstance(rows, list):
        for i, row in enumerate(rows):
            if row is None or not isinstance(row, dict):
                raise ValueError(
                    f"canonical.transactions[{i}] is {row!r}, so this request body was "
                    f"truncated in transit ({len(rows)} rows arrived). Do not resend the "
                    "canonical batch: call extract_and_normalize and pass the batch_id "
                    "it returns instead of canonical."
                )

    classifications = _as_classification_payload(classifications)
    items = classifications.get("classifications")
    if isinstance(items, list):
        for i, item in enumerate(items):
            if item is None or not isinstance(item, dict):
                raise ValueError(
                    f"classifications[{i}] is {item!r}, so this request body was truncated "
                    f"in transit ({len(items)} classifications arrived). Classify in "
                    "smaller batches rather than resending this one."
                )
            if not item.get("transaction_id") and not item.get("merchant"):
                raise ValueError(
                    f"classifications[{i}] names neither a transaction_id nor a merchant: "
                    f"{sorted(item)!r}. Every classification must say what it classifies - "
                    "a `merchant` from the worklist, or a `transaction_id` for one row."
                )


def _slim_summary_for_http(summary: dict, body: dict) -> dict:
    """Drop row arrays Foundry cannot ingest. Full payload stays on summary_id."""
    if body.get("include_full_summary"):
        return summary
    arrays = (
        ("report_view", "include_report_view", "report_view_omitted", None),
        ("part2", "include_part2", "part2_omitted", "part2_row_count"),
        ("part3", "include_part3", "part3_omitted", "part3_row_count"),
        (
            "part2_calculations",
            "include_part2_calculations",
            "part2_calculations_omitted",
            "part2_calculations_row_count",
        ),
    )
    for key, flag, omitted, count_key in arrays:
        if body.get(flag):
            continue
        value = summary.pop(key, None)
        summary[omitted] = True
        if count_key:
            summary[count_key] = len(value) if isinstance(value, list) else 0
    return summary


@app.route(route="compute_summary", methods=["POST"])
def compute_summary_http(req: func.HttpRequest) -> func.HttpResponse:
    """Totals from a canonical batch plus the model's classifications.

    Prefer `batch_id`: name the batch extract_and_normalize already stored and
    the server reads it itself. Passing `canonical` inline still works for
    scripts that hold it, but an agent cannot carry a real binder's batch - it
    is hundreds of kilobytes, and the tool call is truncated mid-array.
    """
    try:
        body = _json(req)
        classifications = _as_classification_payload(body.get("classifications"))
        batch_id = body.get("batch_id")
        # Repair passes send only what they just classified. Without this the
        # agent has to resend all 238 merchants every time, which is what ran
        # it out of context window on a real binder.
        merge_store = bool(body.get("merge_classifications"))
        store_stats = None
        if merge_store:
            if not batch_id:
                raise ValueError(
                    "merge_classifications needs batch_id: the accumulated set "
                    "is keyed by the batch it belongs to"
                )
            merged_rows, store_stats = _merge_classifications(
                batch_id, classifications.get("classifications") or []
            )
            classifications = {**classifications, "classifications": merged_rows}

        if batch_id:
            canonical = _load_batch(batch_id)
        else:
            canonical = body.get("canonical") or {}
            if not canonical.get("transactions"):
                raise ValueError(
                    "supply batch_id (preferred) or a canonical batch with transactions; "
                    "compute_summary has nothing to total"
                )

        _check_not_truncated(canonical, classifications)
        summary = compute_summary(canonical, classifications)
        if store_stats is not None:
            summary["classification_store"] = store_stats

        # Same reason as batch_id: the summary is hundreds of rows, and the
        # caller cannot carry it to render_report. Asked to, a model trims it
        # and leaves `"... trimmed for brevity ..."` sitting in part2 where a
        # row should be. Hand back an id and let the server keep the summary.
        try:
            summary["summary_id"] = _store_batch(summary)
        except Exception as exc:  # noqa: BLE001
            summary["summary_id"] = None
            summary["summary_store_error"] = str(exc)
        # Store FIRST so render_report still has the full ledger + report_view.
        # Then drop the row arrays Foundry cannot ingest (report_view, part2,
        # part3, part2_calculations). Scripts pass include_full_summary or the
        # individual include_* flags.
        _slim_summary_for_http(summary, body)
        return _ok(summary)
    except BatchNotFound as exc:
        return _err(str(exc), status=404)
    except Exception as exc:
        return _err(str(exc), status=400)


def _check_summary_intact(summary: dict) -> None:
    """Catch a summary that was abbreviated on the way in.

    A model asked to resend hundreds of rows will summarise instead, and the
    tell is a bare string sitting where a row object belongs:
    `"part2": [{...}, "... trimmed for brevity in this call ..."]`. Rendering
    that produces a workbook missing most of its line items, so refuse - and
    name `summary_id`, which is how the caller avoids carrying rows at all.
    """
    for key in ("part1", "part2", "part2_calculations", "part3", "part4", "income"):
        rows = summary.get(key)
        if not isinstance(rows, list):
            continue
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(
                    f"summary.{key}[{i}] is {row!r}, not a row. The summary was "
                    "abbreviated instead of sent whole. Do not resend the summary: "
                    "pass the `summary_id` that compute_summary returned."
                )


def _xlsx_base64(summary: dict, applicant: dict | None = None) -> str:
    return base64.b64encode(build_workbook(summary, applicant)).decode("ascii")


def _publish_artifact(artifact: dict, include_base64: bool) -> dict:
    published = _publish_report(
        artifact["content"],
        artifact["filename"],
        content_type=artifact["content_type"],
    )
    published["status"] = "ok"
    published["format"] = artifact["kind"]
    if include_base64:
        key = "xlsx_base64" if artifact["kind"] == "xlsx" else "html_base64"
        published[key] = base64.b64encode(artifact["content"]).decode()
    return published


@app.route(route="render_report", methods=["POST"])
def render_report(req: func.HttpRequest) -> func.HttpResponse:
    """Write the lender report and return a link the caller can hand over.

    `format` is xlsx (default, existing callers), html, or both. Top-level
    `download_url` stays the workbook when format is xlsx or both.

    Returns `download_url` by default. `include_base64: true` additionally
    returns the bytes, for scripts that want them in-process - an agent should
    never ask for it: it cannot write the bytes anywhere, and one encoded
    workbook is thousands of tokens of context spent on nothing.
    """
    try:
        body = _json(req)
        summary_id = body.get("summary_id")
        if summary_id:
            summary = _load_batch(summary_id)
        else:
            summary = body.get("summary") or {}
            _check_summary_intact(summary)
        fmt = body.get("format") or "xlsx"
        artifacts = build_report_artifacts(
            summary, body.get("applicant"), fmt, body.get("filename")
        )

        published_list = []
        include_base64 = bool(body.get("include_base64"))
        for artifact in artifacts:
            try:
                published_list.append(_publish_artifact(artifact, include_base64))
            except ExtractionError as exc:
                first = artifacts[0]
                return _ok(
                    {
                        "filename": first["filename"],
                        "download_url": None,
                        "status": "not_published",
                        "message": f"report rendered but could not be published: {exc}",
                        "size_bytes": len(first["content"]),
                        "format": first["kind"],
                    },
                    status=200,
                )

        if fmt == "both":
            by_kind = {item["format"]: item for item in published_list}
            xlsx = by_kind["xlsx"]
            html = by_kind["html"]
            payload = dict(xlsx)
            payload.update(
                {
                    "html_filename": html["filename"],
                    "html_download_url": html["download_url"],
                    "html_expires_at": html.get("expires_at"),
                    "html_size_bytes": html["size_bytes"],
                    "formats": ["xlsx", "html"],
                }
            )
            if include_base64 and "html_base64" in html:
                payload["html_base64"] = html["html_base64"]
            return _ok(payload)
        return _ok(published_list[0])
    except Exception as exc:
        return _err(str(exc), status=400)
