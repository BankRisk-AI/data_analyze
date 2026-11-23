"""The processing module on its own:  python -m app.modules.eba_processing <serve|validate|config>"""
from __future__ import annotations

import argparse
import json
import sys

from app.core.config import get_schema


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.modules.eba_processing", description="Preview, profile, charts and validation of staged EBA data")
    sub = ap.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="start the HTTP API of this module alone")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8001)
    val = sub.add_parser("validate", help="run the validation of an import now, without the worker, and print the result")
    val.add_argument("import_id", type=int)
    val.add_argument("--json", action="store_true", help="print the whole report")
    sub.add_parser("config", help="print limits, enumerations and the rule catalogue")
    a = ap.parse_args(argv)

    if a.cmd == "serve":
        import uvicorn
        from app.modules.eba_processing.presentation.app import create_app
        uvicorn.run(create_app(get_schema()), host=a.host, port=a.port)
        return 0
    if a.cmd == "config":
        from app.modules.eba_processing.domain import (
            AGGREGATIONS, CLIPS, DEFAULT_BINS, DEFAULT_PAGE_SIZE, DEFAULT_SCATTER_POINTS,
            DEFAULT_TOP_VALUES, MAX_BINS, MAX_PAGE_SIZE, MAX_SCATTER_POINTS, MAX_TOP_VALUES,
            QUERY_TIMEOUT_SECONDS, RULES, SCALES, SEVERITIES,
        )
        config = {
            "default_page_size": DEFAULT_PAGE_SIZE, "max_page_size": MAX_PAGE_SIZE,
            "default_bins": DEFAULT_BINS, "max_bins": MAX_BINS,
            "default_scatter_points": DEFAULT_SCATTER_POINTS, "max_scatter_points": MAX_SCATTER_POINTS,
            "max_top_values": MAX_TOP_VALUES, "query_timeout_seconds": QUERY_TIMEOUT_SECONDS,
            "aggregations": list(AGGREGATIONS), "scales": list(SCALES),
            "clips": list(CLIPS), "severities": list(SEVERITIES),
            "column_roles": ["key", "label", "measure", "annotation", "dimension"],
            "validation_rules": [{"id": r.id, "title": r.title, "severity": r.severity, "description": r.description} for r in RULES],
        }
        print(json.dumps(config, indent=2))
        return 0
    from app.core.exceptions import AppError
    from app.modules.eba_processing.application.validation import report_to_dict, run_validation
    try:
        report = report_to_dict(run_validation(a.import_id, get_schema(), emit=lambda message, percent: print(f"  {percent:3d}%  {message}", file=sys.stderr)))
    except AppError as e:
        print(f"REFUSED ({e.kind}): {e.detail}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(report, indent=2))
        return 0 if report["summary"]["can_proceed"] else 3
    s = report["summary"]
    print(f"import {a.import_id}: {s['errors']} errors, {s['warnings']} warnings, {s['infos']} notes in {report['seconds']} s -> {'can proceed' if s['can_proceed'] else 'cannot proceed'}")
    for f in report["files"]:
        print(f"  {f['file_name']} ({f['rows']:,} rows)")
        for i in f["issues"]:
            if i["status"] == "failed":
                print(f"    {i['rule']} {i['severity']:7} {i['affected_rows']:>9,}  {i['detail']}")
    return 0 if s["can_proceed"] else 3


if __name__ == "__main__":
    sys.exit(main())
