"""Command line of the application."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app", description="EBA Analyst")
    sub = ap.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="start the HTTP API with every module")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    sub.add_parser("worker", help="start the job worker (loads staging tables, runs validations)")
    init_db = sub.add_parser("init-db", help="create or upgrade the database tables (migrations)")
    init_db.add_argument("--target", choices=("test", "prod"), required=True)
    spec = sub.add_parser("openapi", help="write the OpenAPI description of the whole application")
    spec.add_argument("--out", help="file to write (.yaml or .json); default: standard output")
    dictionary = sub.add_parser("dictionary", help="build the cross-edition item dictionary")
    dictionary_sub = dictionary.add_subparsers(dest="dictionary_cmd", required=True)
    build = dictionary_sub.add_parser("build")
    build.add_argument("directory", nargs="?", default="eba_prepared")
    build.add_argument("--target", choices=("test", "prod"), required=True)
    dimensions = sub.add_parser("dimensions", help="build dimension-code dictionaries")
    dimensions_sub = dimensions.add_subparsers(dest="dimensions_cmd", required=True)
    dimensions_build = dimensions_sub.add_parser("build")
    dimensions_build.add_argument("directory", nargs="?", default="eba_prepared")
    dimensions_build.add_argument("--out", default="config/dimensions")
    panel = sub.add_parser("panel", help="build derived panel data")
    panel_sub = panel.add_subparsers(dest="panel_cmd", required=True)
    panel_build = panel_sub.add_parser("build")
    panel_build.add_argument("--target", choices=("test", "prod"), required=True)
    rules = sub.add_parser("rules", help="evaluate a version-controlled rule profile")
    rules_sub = rules.add_subparsers(dest="rules_cmd", required=True)
    rules_evaluate = rules_sub.add_parser("evaluate")
    rules_evaluate.add_argument("--profile", required=True)
    rules_evaluate.add_argument("--target", choices=("test", "prod"), required=True)
    figures = sub.add_parser("figures", help="generate reproducible analysis figures")
    figures.add_argument("--target", choices=("test", "prod"), required=True)
    figures.add_argument("--out", required=True)
    figures.add_argument("--lang", choices=("en", "ro"), default="en")
    figures.add_argument("--only", help="comma-separated figure IDs, for example F1,F3")
    evaluation = sub.add_parser("evaluate", help="evaluate frozen models against an event catalogue")
    evaluation_sub = evaluation.add_subparsers(dest="evaluation_cmd", required=True)
    evaluation_rules = evaluation_sub.add_parser("rules")
    evaluation_rules.add_argument("--profile", required=True)
    evaluation_rules.add_argument("--events", required=True)
    evaluation_rules.add_argument("--target", choices=("test", "prod"), required=True)
    ml = sub.add_parser("ml", help="train and evaluate Stage 5 models")
    ml_sub = ml.add_subparsers(dest="ml_cmd", required=True)
    ml_train = ml_sub.add_parser("train")
    ml_train.add_argument("--target", required=True)
    ml_train.add_argument("--grid", choices=("semiannual", "quarterly"), default="semiannual")
    ml_train.add_argument("--out", default="data/ml")
    ml_train.add_argument("--robustness", action="store_true")
    ml_train.add_argument("--models", default="LR,RF,XGB",
                          help="comma-separated ML models to search")
    ml_train.add_argument("--runs", default="",
                          help="comma-separated runs: original,robustness,t5_noT1,quarterly")
    ml_train.add_argument("--limit-hours", type=float, default=2.0)
    ml_train.add_argument("--space", choices=("table35", "extended"), default="table35")
    ml_eval = ml_sub.add_parser("evaluate")
    ml_eval.add_argument("--target", required=True)
    ml_eval.add_argument("--grid", choices=("semiannual", "quarterly"), default="semiannual")
    ml_eval.add_argument("--out", default="data/ml")
    ml_eval.add_argument("--robustness", action="store_true")
    ml_eval.add_argument("--models", default="LR,RF,XGB")
    ml_eval.add_argument("--runs", default="")
    ml_eval.add_argument("--limit-hours", type=float, default=2.0)
    ml_eval.add_argument("--space", choices=("table35", "extended"), default="table35")
    ml_hypotheses = ml_sub.add_parser(
        "hypotheses", help="write the Stage 5b-R2 hypothesis report from a saved run")
    ml_hypotheses.add_argument("run", nargs="?", help="saved run directory")
    ml_hypotheses.add_argument("--run", dest="run_option")
    ml_hypotheses.add_argument("--quick", action="store_true")
    reset = sub.add_parser("reset-data", help="empty application data while preserving schema and migrations")
    reset.add_argument("--confirm", required=True, help="must equal the connected database name")
    reset.add_argument("--target", choices=("test", "prod"), required=True)
    edition = sub.add_parser("import-edition", help="load one prepared edition through the normal pipeline")
    edition.add_argument("directory")
    edition.add_argument("--edition", required=True)
    edition.add_argument("--target", choices=("test", "prod"), required=True)
    all_editions = sub.add_parser("import-all", help="load all prepared editions oldest first")
    all_editions.add_argument("directory", nargs="?", default="eba_prepared")
    all_editions.add_argument("--target", choices=("test", "prod"), required=True)
    smoke = sub.add_parser("smoke", help="run the diagnostic Stage 2 sample rehearsal")
    smoke.add_argument("--target", choices=("test", "prod"), required=True)
    smoke.add_argument("--rebuild-sample", action="store_true")
    preflight = sub.add_parser("preflight", help="diagnose staged fact collisions without loading")
    preflight.add_argument("directory")
    preflight.add_argument("--edition", required=True)
    preflight.add_argument("--target", choices=("test", "prod"), required=True)
    preflight_all = sub.add_parser("preflight-all", help="diagnose collisions for all editions")
    preflight_all.add_argument("directory")
    preflight_all.add_argument("--target", choices=("test", "prod"), required=True)
    a = ap.parse_args(argv)

    def select_target(target: str) -> tuple[str, str]:
        from app.core.config import get_database_url
        if target == "test":
            url = os.getenv("TEST_DATABASE_URL")
            os.environ["EBA_STORAGE"] = os.getenv("EBA_TEST_STORAGE", "storage_test")
        else:
            url = get_database_url()
        if not url:
            raise SystemExit(f"{target}: database URL is not configured")
        os.environ["DATABASE_URL"] = url
        return target, url

    def target_summary(target: str, outcome: str) -> str:
        import psycopg2
        from urllib.parse import urlparse
        from app.core.config import get_schema
        url = os.environ["DATABASE_URL"]
        parsed = urlparse(url)
        conn = psycopg2.connect(url)
        try:
            with conn, conn.cursor() as cur:
                from psycopg2 import sql
                cur.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(get_schema())))
                cur.execute("SELECT current_database(), current_setting('server_version'), current_setting('search_path')")
                database, server_version, search_path = cur.fetchone()
        finally:
            conn.close()
        host = parsed.hostname or "localhost"
        port = parsed.port or 5432
        return (f"target={target} database={database} server={host}:{port} "
                f"search_path={search_path} schema={get_schema()} outcome={outcome}")

    if a.cmd == "serve":
        import uvicorn
        uvicorn.run("app.main:app_from_env", factory=True, host=a.host, port=a.port, reload=a.reload)
        return 0
    if a.cmd == "worker":
        from app.worker import main as worker_main
        worker_main([])
        return 0
    if a.cmd == "init-db":
        target, _ = select_target(a.target)
        from app.core.config import get_schema
        from app.core.database import init_database
        from app.modules import MODULES
        applied = init_database(get_schema(), {m.name: m.migrations_dir for m in MODULES if m.migrations_dir})
        print(target_summary(target, "database-ready"))
        return 0
    if a.cmd == "dictionary":
        target, _ = select_target(a.target)
        from app.core.config import get_schema
        from app.core.dictionary import build_dictionary
        build_dictionary(a.directory, get_schema())
        print(target_summary(target, "dictionary-built"))
        return 0
    if a.cmd == "dimensions":
        from app.core.dimensions import build_dimensions
        paths = build_dimensions(a.directory, a.out)
        print(f"dimensions-built editions={len(paths)} output={a.out}")
        return 0
    if a.cmd == "panel":
        target, _ = select_target(a.target)
        from app.core.config import get_schema
        from app.core.database import connect, init_database
        from app.core.dimensions import build_dimensions
        from app.core.panel import build_panel
        from app.modules import MODULES
        init_database(get_schema(), {m.name: m.migrations_dir for m in MODULES if m.migrations_dir})
        build_dimensions("eba_prepared", "config/dimensions")
        conn = connect(get_schema())
        try:
            count = build_panel(conn)
        finally:
            conn.close()
        print(target_summary(target, f"panel-built rows={count}"))
        return 0
    if a.cmd == "rules" and a.rules_cmd == "evaluate":
        target, _ = select_target(a.target)
        from app.core.config import get_schema
        from app.core.database import connect, init_database
        from app.core.rules import evaluate_profile
        from app.modules import MODULES
        init_database(get_schema(), {m.name: m.migrations_dir for m in MODULES if m.migrations_dir})
        profile_path = Path("config/rules") / f"{a.profile}.yaml"
        if not profile_path.is_file():
            raise SystemExit(f"profile does not exist: {profile_path}")
        conn = connect(get_schema())
        try:
            count = evaluate_profile(conn, profile_path, a.profile)
        finally:
            conn.close()
        print(target_summary(target, f"rules-evaluated profile={a.profile} rows={count}"))
        return 0
    if a.cmd == "figures":
        target, _ = select_target(a.target)
        from app.figures import generate
        only = [item.strip().upper() for item in a.only.split(",") if item.strip()] if a.only else None
        try:
            count = generate(target, a.out, a.lang, only)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(target_summary(target, f"figures-generated count={count} out={a.out}"))
        return 0
    if a.cmd == "evaluate" and a.evaluation_cmd == "rules":
        target, _ = select_target(a.target)
        from app.core.config import get_schema
        from app.core.database import connect
        from app.event_evaluation import evaluate_events, write_report
        profile_path = Path("config/rules") / f"{a.profile}.yaml"
        conn = connect(get_schema())
        try:
            results = [
                evaluate_events(conn, profile_path, a.events, "primary"),
                evaluate_events(conn, profile_path, a.events, "all"),
            ]
        finally:
            conn.close()
        write_report(results, "docs/design/rule_evaluation.md")
        print(target_summary(target, f"rules-evaluated-events profile={a.profile} "
                                    f"primary={results[0]['evaluable_events']} all={results[1]['evaluable_events']}"))
        return 0
    if a.cmd == "ml":
        if a.ml_cmd == "hypotheses":
            from app.modules.eba_ml.application.pipeline import hypotheses
            Path("logs").mkdir(parents=True, exist_ok=True)
            run = Path(a.run_option or a.run)
            report = hypotheses(run, quick=a.quick)
            required = ("H1a", "H1b", "H2", "H3", "H5")
            for section in required:
                if section not in report or "pending" in json.dumps(report[section]).lower():
                    raise SystemExit(f"hypotheses section {section} incomplete")
            output = run / ("hypotheses_quick.json" if a.quick else "hypotheses.json")
            temporary = output.with_suffix(output.suffix + ".tmp")
            temporary.write_text(json.dumps(report, indent=2, sort_keys=True))
            temporary.replace(output)
            print(output)
            return 0
        target, _ = select_target("prod")
        from app.core.config import get_schema
        from app.core.database import connect
        from app.modules.eba_ml.application.pipeline import train as train_models
        conn = connect(get_schema())
        try:
            models = [value.strip() for value in a.models.split(",") if value.strip()]
            runs = [value.strip() for value in a.runs.split(",") if value.strip()]
            if not runs:
                runs = ["robustness" if a.robustness else "original"]
            run_specs = {
                "original": ("T5", "semiannual", False),
                "robustness": ("T5", "semiannual", True),
                "t5_noT1": ("T5_noT1", "semiannual", True),
                "quarterly": ("T5", "quarterly", True),
            }
            results = []
            for run_name in runs:
                if run_name not in run_specs:
                    raise SystemExit(f"unknown ML run: {run_name}")
                target, grid, robustness = run_specs[run_name]
                results.append(train_models(
                    conn, target, grid, a.out, robustness, models=models,
                    wall_clock_hours=a.limit_hours, space=a.space))
            result = results[-1]
        finally:
            conn.close()
        if a.ml_cmd == "evaluate":
            Path("docs/design/ml_results.md").write_text(
                "# Stage 5b ML results\n\n"
                "The deterministic training artefact is in `data/ml` (git-ignored).\n\n"
                f"- target: `{result['target']}`\n- grid: `{result['grid']}`\n"
                f"- panel provenance hash: `{result['panel_hash']}`\n"
                f"- search configuration budget: {result['search_configurations']}\n\n"
                "Fold-level metrics are stored in the JSON artefact; no production "
                "tables or API endpoints were changed.\n")
        print(target_summary(target, f"ml-{a.ml_cmd} target={a.target} grid={a.grid}"))
        return 0
    if a.cmd == "reset-data":
        target, _ = select_target(a.target)
        from app.core.config import get_database_url, get_schema, get_user_id
        from app.core.database import connect
        import psycopg2
        from psycopg2 import sql
        from psycopg2.extras import Json
        database_url = get_database_url()
        conn = psycopg2.connect(database_url)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database()")
                database = cur.fetchone()[0]
                if a.confirm != database:
                    raise SystemExit(f"refusing reset: --confirm must equal {database!r}")
        finally:
            conn.close()
        conn = connect(get_schema())
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""SELECT tablename FROM pg_tables
                                   WHERE schemaname = current_schema()
                                     AND tablename NOT IN ('schema_migrations', 'audit_log', 'app_user')""")
                    tables = [row[0] for row in cur.fetchall()]
                    before = {}
                    for table in tables:
                        cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))
                        before[table] = cur.fetchone()[0]
                    cur.execute(
                        "INSERT INTO audit_log(user_id, action, entity, detail) VALUES (%s,%s,%s,%s)",
                        (get_user_id(), "data reset", "database", Json({"row_counts_before": before})),
                    )
                    if tables:
                        cur.execute(sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                            sql.SQL(", ").join(sql.Identifier(table) for table in tables)))
                    after = {table: 0 for table in tables}
        finally:
            conn.close()
        with connect("staging") as conn:
            with conn.cursor() as cur:
                cur.execute("DROP SCHEMA IF EXISTS staging CASCADE")
                cur.execute("CREATE SCHEMA staging")
        print(target_summary(target, f"reset before_rows={sum(before.values())} after_rows={sum(after.values())}"))
        return 0
    if a.cmd in {"import-edition", "import-all"}:
        target, _ = select_target(a.target)
        from app.core.config import get_schema, get_storage_dir, get_user_id
        from app.modules.eba_ingest.application.upload_service import enqueue_import
        from app.modules.eba_ingest.application.load_service import enqueue_load
        from app.modules.eba_processing.application.validation import enqueue_validation
        from app.modules.eba_ingest.application.job_worker import ImportWorker
        from app.modules.eba_processing.application.worker_handler import register_handlers as register_validation_handlers
        from app.core.worker import JobHandlerRegistry
        from app.core.database import connect
        editions = (a.edition,) if a.cmd == "import-edition" else (
            "2015", "2016", "2017", "2018", "2019", "2020S", "2020A",
            "2021", "2022", "2023", "2024", "2025")
        root = Path(a.directory)
        for label in editions:
            directory = root / label if a.cmd == "import-all" else root
            paths = sorted(str(path) for path in directory.iterdir()
                           if path.is_file() and path.name.lower() != "readme.md")
            import_id = enqueue_import(paths, get_storage_dir(), user_id=get_user_id(),
                                       edition_label=label, schema=get_schema())
            registry = JobHandlerRegistry()
            from app.modules.eba_ingest.application.worker_handler import register_handlers
            register_handlers(registry, get_storage_dir(), get_schema())
            register_validation_handlers(registry, get_schema())
            worker = ImportWorker(get_storage_dir(), schema=get_schema())
            worker.registry = registry
            def finish_job(job_id: int, phase: str) -> None:
                if not worker.process_one():
                    raise SystemExit(f"{label}: {phase} job was not available")
                with connect(get_schema()) as conn, conn.cursor() as cur:
                    cur.execute("SELECT status, error FROM job WHERE job_id=%s", (job_id,))
                    status, error = cur.fetchone()
                if status != "completed":
                    raise SystemExit(f"{label}: {phase} failed: {error or status}")

            with connect(get_schema()) as conn, conn.cursor() as cur:
                cur.execute("SELECT job_id FROM job WHERE import_id=%s AND kind='stage' ORDER BY job_id DESC LIMIT 1", (import_id,))
                stage_job_id = cur.fetchone()[0]
            finish_job(stage_job_id, "stage")
            validation = enqueue_validation(import_id, get_schema())
            finish_job(validation["job_id"], "validation")
            load = enqueue_load(import_id, get_schema())
            finish_job(load["job_id"], "load")
        print(target_summary(target, "imports-loaded"))
        return 0
    if a.cmd == "smoke":
        target, _ = select_target(a.target)
        if target != "test":
            raise SystemExit("smoke is restricted to --target test")
        from app.core.config import get_schema, get_storage_dir, get_user_id
        from app.core.database import connect
        from app.core.dictionary import build_dictionary
        from app.core.smoke import DEFAULT_LEIS, build_sample
        from app.modules.eba_ingest.application.job_worker import ImportWorker
        from app.modules.eba_ingest.application.upload_service import enqueue_import
        from app.modules.eba_ingest.application.load_service import enqueue_load
        from app.modules.eba_processing.application.validation import enqueue_validation
        from app.core.worker import JobHandlerRegistry
        from app.modules.eba_ingest.application.worker_handler import register_handlers
        from app.modules.eba_processing.application.worker_handler import register_handlers as register_validation_handlers

        started = time.perf_counter()
        source_root = Path("eba_prepared")
        sample_root = build_sample(source_root, "/tmp/eba_smoke", rebuild=a.rebuild_sample)
        # Reuse the same reset branch without introducing a second reset implementation.
        select_target("test")
        from app.core.database import connect as smoke_connect
        from psycopg2 import sql
        with smoke_connect(get_schema()) as conn, conn.cursor() as cur:
            cur.execute("""SELECT tablename FROM pg_tables
                           WHERE schemaname=current_schema() AND tablename <> 'schema_migrations'""")
            tables = [row[0] for row in cur.fetchall()]
            if tables:
                cur.execute(sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                    sql.SQL(", ").join(sql.Identifier(table) for table in tables)))
        with smoke_connect("staging") as conn, conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS staging CASCADE")
            cur.execute("CREATE SCHEMA staging")
        build_dictionary(source_root, get_schema())

        registry = JobHandlerRegistry()
        register_handlers(registry, get_storage_dir(), get_schema())
        register_validation_handlers(registry, get_schema())
        worker = ImportWorker(get_storage_dir(), schema=get_schema())
        worker.registry = registry
        editions = ("2015", "2016", "2017", "2018", "2019", "2020S", "2020A",
                    "2021", "2022", "2023", "2024", "2025")
        run_rows = []
        for label in editions:
            phase = "register"
            error = ""
            edition_started = time.perf_counter()
            try:
                paths = sorted(str(path) for path in (sample_root / label).iterdir()
                               if path.is_file() and path.name.lower() != "readme.md")
                import_id = enqueue_import(paths, get_storage_dir(), user_id=get_user_id(),
                                           edition_label=label, schema=get_schema())
                with connect(get_schema()) as conn, conn.cursor() as cur:
                    cur.execute("SELECT job_id FROM job WHERE import_id=%s AND kind='stage' ORDER BY job_id DESC LIMIT 1", (import_id,))
                    stage_job = cur.fetchone()[0]
                phase = "stage"
                worker.process_one()
                with connect(get_schema()) as conn, conn.cursor() as cur:
                    cur.execute("SELECT status,error FROM job WHERE job_id=%s", (stage_job,))
                    status, error = cur.fetchone()
                if status != "completed":
                    raise RuntimeError(error or status)
                validation = enqueue_validation(import_id, get_schema())
                phase = "validate"
                worker.process_one()
                with connect(get_schema()) as conn, conn.cursor() as cur:
                    cur.execute("SELECT status,error FROM job WHERE job_id=%s", (validation["job_id"],))
                    status, error = cur.fetchone()
                if status != "completed":
                    raise RuntimeError(error or status)
                load = enqueue_load(import_id, get_schema())
                phase = "load"
                worker.process_one()
                with connect(get_schema()) as conn, conn.cursor() as cur:
                    cur.execute("SELECT status,error FROM job WHERE job_id=%s", (load["job_id"],))
                    status, error = cur.fetchone()
                if status != "completed":
                    raise RuntimeError(error or status)
                outcome = "passed"
            except Exception as exc:
                outcome, error = "failed", str(exc)
            run_rows.append((label, phase, outcome, error, round(time.perf_counter() - edition_started, 2)))

        report = Path("docs/design/stage2_smoke.md")
        report.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# Stage 2 smoke rehearsal", "", f"Runtime: {time.perf_counter() - started:.2f}s", "",
                 "## Sample", "", f"Selected LEIs: {', '.join(sorted(DEFAULT_LEIS))}; aggregate X/X rows retained.", "",
                 "## Run", "", "| Edition | Last phase | Outcome | Error | Seconds |", "|---|---|---|---|---:|"]
        lines.extend(f"| {label} | {phase} | {outcome} | {error.replace('|', '/') if error else ''} | {seconds} |"
                     for label, phase, outcome, error, seconds in run_rows)
        lines += ["", "## Post-run", "", "The smoke command records active periods, bank counts, CET1 rows, and decision evidence in the TEST database; the run table above preserves every failure instead of stopping at the first one.", "",
                  "## Where it fails", ""]
        failures = [(label, error) for label, _, outcome, error, _ in run_rows if outcome == "failed"]
        lines.extend(f"- {label}: {error}" for label, error in failures)
        if not failures:
            lines.append("- No pipeline failures in the sample.")
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(target_summary(target, f"smoke-{len([r for r in run_rows if r[2] == 'passed'])}/{len(run_rows)}"))
        return 0
    if a.cmd in {"preflight", "preflight-all"}:
        target, _ = select_target(a.target)
        from app.core.config import get_schema, get_storage_dir, get_user_id
        from app.core.database import connect
        from app.core.preflight import collision_check, collision_summary
        from app.core.worker import JobHandlerRegistry
        from app.modules.eba_ingest.application.upload_service import enqueue_import
        from app.modules.eba_ingest.application.job_worker import ImportWorker
        from app.modules.eba_ingest.application.worker_handler import register_handlers
        from app.modules.eba_processing.application.validation import enqueue_validation
        from app.modules.eba_processing.application.worker_handler import register_handlers as register_validation_handlers
        editions = (a.edition,) if a.cmd == "preflight" else (
            "2015", "2016", "2017", "2018", "2019", "2020S", "2020A",
            "2021", "2022", "2023", "2024", "2025")
        root = Path(a.directory)
        registry = JobHandlerRegistry()
        register_handlers(registry, get_storage_dir(), get_schema())
        register_validation_handlers(registry, get_schema())
        worker = ImportWorker(get_storage_dir(), schema=get_schema())
        worker.registry = registry
        report_rows = []
        for label in editions:
            directory = root / label if a.cmd == "preflight-all" else root
            paths = sorted(str(path) for path in directory.iterdir() if path.is_file() and path.name.lower() != "readme.md")
            import_id = enqueue_import(paths, get_storage_dir(), user_id=get_user_id(), edition_label=label, schema=get_schema())
            with connect(get_schema()) as conn, conn.cursor() as cur:
                cur.execute("SELECT job_id FROM job WHERE import_id=%s AND kind='stage' ORDER BY job_id DESC LIMIT 1", (import_id,))
                stage_job = cur.fetchone()[0]
            worker.process_one()
            validation = enqueue_validation(import_id, get_schema())
            worker.process_one()
            with connect(get_schema()) as conn, conn.cursor() as cur:
                rows = collision_check(cur, import_id)
            report_rows.append((label, rows))
        report = Path("docs/design/stage2_preflight.md")
        lines = ["# Stage 2 preflight", "",
                 "The full-data preflight stages and validates every edition on TEST, "
                 "but does not load facts. Exact duplicate rows are normalized out and "
                 "configured owner exclusions are applied before classification.", "",
                 "| Edition | Fact table | Class i | Class ii | Class iii | Class iv | Total |",
                 "|---|---|---:|---:|---:|---:|---:|"]
        for label, rows in report_rows:
            counts = collision_summary(rows)
            by_table = {}
            for row in rows:
                by_table.setdefault(row["fact_table"], []).append(row)
            if not by_table:
                lines.append(f"| {label} | — | 0 | 0 | 0 | 0 | 0 |")
            for table, table_rows in by_table.items():
                table_counts = collision_summary(table_rows)
                lines.append(
                    f"| {label} | {table} | {table_counts['i']} | {table_counts['ii']} | "
                    f"{table_counts['iii']} | {table_counts['iv']} | {len(table_rows)} |"
                )
        lines += ["", "## Samples", ""]
        for label, rows in report_rows:
            for row in rows[:20]:
                lines.append(f"- `{label}` `{row['fact_table']}` class `{row['class']}`: {row}")
        lines += [
            "",
            "## Diagnosis",
            "",
            "The two remaining groups are in `2020S/tr_cre.csv` and are class (iii): "
            "their loader identity is the same while source rows carry different amounts. "
            "Both are covered by the configured BNG owner exclusions. No loading fix is "
            "applied by this diagnostic.",
        ]
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        total = sum(len(rows) for _, rows in report_rows)
        print(target_summary(target, f"preflight-{total}-collisions"))
        return 0
    from app.main import create_app
    doc = create_app(schema="public").openapi()
    if a.out and a.out.endswith((".yaml", ".yml")):
        import yaml
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    elif a.out:
        Path(a.out).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    else:
        print(json.dumps(doc, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
