# `eba_ml` module design (Stage 5e)

This document records the approved Stage 5e-1 design and implementation. The
The API and worker handlers are implemented. The module
will follow the existing `ModuleSpec` boundary and the dependency direction
`domain -> application -> infrastructure -> presentation`. The current
database has 16 logical tables; the implementation adds four ML-owned tables, for 20
logical tables total. Existing `panel_row`, `alert`, `job`, `bank`, and
`dataset_version` remain the sources of panel, rule, job, identity, and
provenance data.

## 1. Domain model and lifecycle

* **Dataset**: target, grid, feature-set identifier and version, panel
  provenance hash, content hash, row count, feature manifest, created time and
  status (`building`, `ready`, `failed`). A dataset is immutable once ready.
* **Experiment/run**: validated configuration, dataset, seed, folds, search
  budget, status (`queued`, `running`, `completed`, `cancelled`, `failed`),
  progress, metrics, event-evaluation results, and artifact references.
* **Model**: experiment, algorithm, hyperparameters, model artifact SHA-256,
  status (`training -> trained -> validated -> champion -> archived`, or
  `failed`), model card, validation metrics and code commit. There is exactly
  one champion for each `(target, grid)`: a protected champion replaced by
  another champion returns to `validated`; a non-protected former champion is
  archived transactionally.
* **Prediction**: model, panel dataset version, period, bank, probability,
  threshold setting, alert boolean and top SHAP contributions. Predictions are
  immutable and keyed by model/bank/period/threshold.

The application layer owns state transitions and champion invariants. Domain
code owns target/grid/feature validation, threshold and metric definitions.
Infrastructure owns repository queries, artifact storage and calls to the
the moved pipeline implementation in `eba_ml`.

## 2. Persistence and artifacts

Four tables are implemented:

| table | essential columns and constraints |
|---|---|
| `ml_dataset` | `id`, target, grid, feature_set, panel hash, content hash, manifest JSON, row count, status, timestamps; unique content hash |
| `ml_experiment` | `id`, dataset FK, config JSON, seed, folds JSON, budget, status/progress, metrics JSON, artifact refs, timestamps |
| `ml_model` | `id`, experiment FK, target/grid, algorithm, hyperparameters JSON, artifact SHA, model-card JSON, status, protected flag, timestamps; partial unique champion `(target,grid)` |
| `ml_prediction` | model FK, dataset version FK, bank FK, period, threshold setting, probability, alert, SHAP JSON; unique model/bank/period/threshold and indexes for bank/period |
Audit entries use the existing `audit_log` table; no ML-specific audit table is added.

Foreign keys to datasets, experiments, banks and dataset versions use
`ON DELETE RESTRICT`; `ml_prediction.model_id` uses `ON DELETE CASCADE` only for
the restricted hard-delete transaction. Archive is the default delete action.
The migration is numbered and idempotent; no Chapter 4 table is changed.

Artifacts live below `EBA_STORAGE/models/<artifact-sha256>/`. The directory
contains a portable sklearn `joblib` or native XGBoost JSON model plus a model
card JSON containing data hash, validated config, metrics, git commit, Python
and library versions, and SHA-256 values. Writes are temporary-then-rename;
loads verify the recorded hash before deserialization. Artifact paths and
filenames are never accepted from the client.

## 3. Protection and deletion

The 5b/5c thesis experiment and its models have `protected=true`. Protected
artefacts, metrics, configs and datasets are immutable and cannot be deleted or
archived; the champion flag may move. When a protected champion is replaced it
returns to `validated`, while a non-protected former champion becomes
`archived`. A normal delete request archives a model. Hard delete is allowed
only for a non-protected, non-champion model and requires the client to send the
exact model name. Its predictions are deleted in the same transaction; the
artifact directory is removed only when no other model references that SHA.
Every create, train, validate, promote, archive and delete operation writes the
existing `audit_log` row.

## 4. Resource limits and worker jobs

The module registers these job kinds with the existing worker:
`build_ml_dataset`, `train_model`, `tune_model`, `evaluate_model`, and
`score_panel`. Only one training or tuning job may be active at a time; the
database advisory lock is acquired before work starts. A tuning job accepts at
most 60 configurations by default (bounded by server configuration), has a
wall-clock limit, and receives a deterministic seed. Handlers report phase and
percentage through the existing job progress fields and check cancellation
between folds/configurations and before artifact promotion.

On restart, a heartbeat-stale job is requeued by the generic worker if retry
capacity remains. Dataset/model writes are idempotent by content/artifact hash.
After the retry limit, the job is marked failed with an explicit message and
partial temporary artifacts are removed; a promoted immutable artifact is
never overwritten.

## 5. API under `/api/ml`

All operations use explicit `operation_id`, summary, tags and the repository
problem+json responses. List endpoints are paginated and default to safe
limits.

| resource | operations |
|---|---|
| datasets | `GET /datasets`, `POST /datasets`, `GET /datasets/{id}` |
| experiments | `GET /experiments`, `POST /experiments`, `GET /experiments/{id}`, `POST /experiments/{id}/cancel` |
| models | `GET /models` (filters), `GET /models/{id}`, `POST /models/compare`, `POST /models/{id}/champion`, `POST /models/{id}/archive`, `DELETE /models/{id}` |
| predictions | `GET /predictions` by period/bank; champion-only by default |
| metadata | `GET /options` for targets, grids, feature sets, algorithms, search spaces and limits |

`POST /experiments` accepts a strict schema: target, grid, feature set,
algorithms, seed, folds, budget and threshold settings. Unknown algorithms,
features, folds, unsafe budgets and mismatched provenance are rejected as
422. The API never accepts arbitrary SQL, Python, artifact paths or model
objects. Detail responses include fold metrics, event evaluation, SHAP,
model-card metadata and job references.

## 6. React screens

The Models registry lists status, target/grid, algorithm, champion/protected
badges, metrics and actions. The experiment wizard selects target, grid,
feature set, algorithms and budget, then shows a validated review before
submission. A job-progress view displays phase, percentage, heartbeat,
cancellation and failure details.

Model detail shows the model card, provenance, fold and pooled metrics, PR
curve, event evaluation, SHAP, artifact verification and predictions. Compare
accepts two to four models with aligned folds and metrics. The bank page and
heatmap show champion probabilities and threshold alerts beside frozen v1.1
rule alerts, with period and bank filters.

## 7. Testing and reproducibility

The module must include a regression test that moves the existing 5b/5c
experiment through the module and reproduces the headline robustness numbers
byte-for-byte or within documented floating-point tolerance (maximum absolute
probability difference `1e-12` for the protected thesis regression). Other tests
cover deterministic dataset/content hashes, panel provenance, artifact
SHA verification, protected/champion deletion rules, exact-name confirmation
expiry, cancellation, stale-job recovery, advisory-lock concurrency, one
champion per target/grid, pagination, and problem+json validation.
The existing event windows, Sarlin metrics, bootstrap seed, SHAP conventions
and fold definitions are reused, not reimplemented.

## 8. Implementation plan

### 5e backend

1. Extract the reusable dataset, training, evaluation, bootstrap and SHAP
   services extracted from `app.ml` behind domain/application ports; add the four-table
   migration, artifact store and regression fixtures.
2. Add `eba_ml` module registration, repositories, worker handlers, lifecycle
   and protection transactions, then expose the `/api/ml` schemas/routes and
   OpenAPI contract. Run the 5b/5c reproducibility suite before enabling
   champion promotion.
3. Add operational limits, cancellation/restart handling, audit reporting and
   production read-only smoke tests.

### 5f UI

1. Build registry, options-driven experiment wizard and job-progress screens.
2. Build detail/compare/model-card/SHAP/event views and prediction overlays.
3. Add protected-model affordances, exact-name confirmation flow, accessibility and
   deterministic API fixture tests.

## Waiting for owner decision

All six decisions are resolved: joblib plus native XGBoost JSON; restricted
hard delete with exact-name confirmation and prediction cascade; one active
training/tuning job per installation; local single-user visibility until
authentication exists; single `operating_point_f2` threshold (frozen F2-maximising
threshold from T3_primary OOF; R0-breach rows scored separately as `r0_breach`);
and promotion of any validated archived model for rollback.

**T-4 (2026-11-25)**: thesis-T3-primary-lr is the champion for (E2_or_E3,
semiannual) with operating_point=0.4916. Old stage5c models (target T5, pre-thesis
definition) are validated+protected with note "superseded by thesis-T3-primary".

### Provenance

The protected thesis models are backfilled from their recorded Stage 5c
configuration using the existing pipeline. An artifact SHA is updated only
after fold probabilities reproduce the stored reference within `1e-12`; a
failed reproduction leaves the registry row unchanged.
