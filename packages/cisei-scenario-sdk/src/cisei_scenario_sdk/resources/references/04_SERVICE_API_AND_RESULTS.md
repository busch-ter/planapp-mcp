# Network-service API and planning results

## Authentication and routing

The client registers through `POST /register?user_id=...`. The response contains
the user ID and token. Authenticated planning calls use the `X-Token` header and
the path prefix `/{user_id}`. SDK and example distribution routes are mounted
on the hub without that user prefix.

The planning worker uses response envelopes:

- success: `{status: "OK", kind: "json", data: ...}`;
- planning failure: `{status: "error", kind: "text", data: "message"}`.

The SDK raises a runtime exception when the envelope status is not OK. HTTP
transport errors are raised by `requests` before envelope processing.

## Staged API

The implemented planning stages are:

1. **Define** — `POST /planning/scenarios/define`
2. **Validate without storing** — `POST /planning/scenarios/validate`
3. **Upload scenario-local configuration** —
   `POST /planning/scenarios/{id}/configuration`
4. **Build candidates** —
   `POST /planning/scenarios/{id}/candidate_edges/build`
5. **Optionally tune cell candidates** —
   `POST /planning/scenarios/{id}/candidate_edges/tune`
6. **Compute or assign metrics** —
   `POST /planning/scenarios/{id}/metrics/compute`
7. **Solve** — `POST /planning/scenarios/{id}/solution/solve`
8. **Evaluate** — `GET /planning/scenarios/{id}/evaluation`
9. **Export result or scenario** — corresponding `/export/result` and
   `/export/scenario` GET endpoints.

There are read endpoints for scenarios, candidates, metrics, and solution, plus
scenario deletion and feature-cache import/export endpoints.

`POST /planning/workflow/run` executes a one-request shortcut using an embedded
scenario dictionary. It can build, optionally tune, compute/assign metrics,
solve, and optionally embed evaluation. It does not implement local project
persistence.


## Candidate-to-metric pipeline

The planner does not evaluate every possible interface pair. Candidate construction
first reduces the search space. For graph planning, scenario connectivity rules and
optional manual candidate edges constrain eligible neighbors; the cell planner can
build primary tower-to-client candidates directly.

For each candidate RF edge that requires computation, the network service requests
raw geographic/propagation features from the features service. The conceptual
pipeline is:

`candidate edge → raw geographic/propagation features → technology-specific metric`

The interface `tech` selects the corresponding `metrics.<tech>` specification. A
multi-technology scenario can therefore evaluate LTE and Wi-SUN edges with different
metric definitions. Built-in metric resources can be referenced directly; workspace
metric TOML files are read locally by the SDK and uploaded as scenario-local
overrides. The service never reads the user's workspace path and the upload does not
modify the server's built-in library.

## Candidate and metric controls

Candidate construction accepts planner `graph` or `cell`, preservation of
manual edges, primary technology, sector awareness, optional distance limit,
and optional neighbor degree.

Metric computation either accepts explicit `{src, dst, metric}` records or
calls the features service. Feature-service controls include URL, worker prefix,
pool size, timeout, and whether expanded features appear in the response.


## Solve semantics: metric versus rank

`solve` operates on the evaluated candidate graph. An edge **metric** is the
cost/quality of one candidate link. A node **rank** is the accumulated cost/quality
of its selected path toward the backhaul. Fixed/connected nodes contribute their
initial rank to downstream paths. The solver therefore produces a topology — parent
relationships, planned edges, and resulting path ranks — rather than merely selecting
individually good links.

## Exported result

The persisted planning result is execution output rather than scenario input.
Its principal fields are:

- `working_crs`;
- `counts` for sites, RPL nodes, candidate edges, metric edges, planned nodes,
  and planned edges;
- `rpl_nodes`;
- `candidate_edges`;
- `metric_edges`;
- optional `edge_features`;
- `planned_nodes`;
- `planned_edges`;
- optional embedded `evaluation`.

Raw features are excluded by default. Portable raw-feature persistence belongs
in `features.json`, separately from `result.json`.

## Deterministic evaluation

Evaluation of a live or serialized result produces:

- `quality_summary`;
- `quality`, one row per interface;
- `service`, assignments for unconnected interfaces of the primary technology;
- `result_edges`, planned edges enriched with endpoint metadata.

Quality classification uses a caller-provided `rank_threshold`:

- connected interface: `connected`;
- no finite planned rank: `unserved`;
- rank at or below threshold: `good`;
- finite rank above threshold: `poor`.

The summary's `success` is true only when there is at least one target and no
poor or unserved target. This is a narrow deterministic criterion, not a full
statement that a design satisfies capacity, redundancy, cost, or business
requirements.


## Evaluation as a project-review signal

`rank_threshold` is applied to the accumulated path result, not to one edge metric.
The deterministic evaluation classifies interfaces as `connected`, `good`, `poor`,
or `unserved`. `poor` and `unserved` mean that the current project does not satisfy
that chosen rank criterion and should be reviewed; they are not merely presentation
labels.

Structured evaluation/result records are the source of truth for review. Plots and
maps are aids for interpreting spatial/network structure. Public report or
visualization helper names must be verified against the SDK/examples before being
documented; do not invent convenience methods.

## API work needed for AI correction

**Gap:** error responses are currently text, so an assistant SDK cannot reliably
map failures to fields or decide whether to retry. A future contract should add
stable error codes, stage, field/path, affected entity, retryability, and
human-readable detail while preserving compatibility for existing clients.

