# Using the current planning software

This is the implemented manual workflow in the 2026-09-24 snapshot. It does not describe an available assistant SDK or MCP server. Consult `01_CURRENT_ARCHITECTURE.md` and `02_WORKSPACE_AND_SDK.md` for ownership and lifecycle, and current source for exact signatures and deployment configuration.

## Prepare a workspace

Call `init_workspace` to create `antennas/`, `metrics/`, `data/`, `notebooks/`, and `projects/`. The planning client associates with this existing workspace; it does not take a project in its constructor. Place a project under `projects/<project_name>/` with `scenario.toml` and, when referenced by `instances`, a `nodes.csv`. `open_project` requires the scenario file and imports a saved `features.json` if present. See `02_WORKSPACE_AND_SDK.md` §§ Workspace layout, Project rules.

## Create `scenario.toml`

Define reusable `antennas.<id>`, `interfaces.<id>`, and `devices.<id>` profiles. Each interface needs `tech`, `freq_mhz`, `tx_power_dbm`, and an `antenna_id` that exists in the scenario. Each device needs a nonempty list of interface profile IDs. Define `metrics.<tech>` for the technologies used by interfaces. Supply sites either as embedded `sites` or with `[instances] source = "nodes.csv"` and a CSV with site ID, coordinates, and a valid `device_profile` per row. The SDK resolves CSV paths relative to the TOML, expands instances into concrete sites, and sends the dictionary to the network service. `scenario.working_crs` supports projected distance calculations. For graph planning, add `net.connectivity` rules or concrete `net.candidate_edges`; cell planning builds cell candidates. Consult `03_SCENARIO_FORMAT.md` for fields and `07_CANONICAL_CASES.md` for the LTE and Wi-SUN examples. Do not infer defaults or required fields from an example alone.

The minimal intake CSV envisaged for the future assistant lacks `device_profile` and cannot yet run directly. The executable project CSV must assign a device profile. Validation of scenario references does not guarantee successful candidate building, antenna lookup, metric compilation, or solving. See `03_SCENARIO_FORMAT.md` §§ Intake CSV versus executable CSV, Current validation scope.

## Run and save

The current staged lifecycle is `client.open_project(project, planner=...)`, then `session.build_candidate_edges(...)`, `session.compute_metrics(...)`, `session.solve()`, `session.evaluate(...)`, and `session.save_result(...)`. Computing metrics persists portable raw features to `features.json`; saving a result writes `result.json`. Local result loading does not restore a live worker scenario. `PlanningClient.evaluate_result` can evaluate an exported result independently. See `02_WORKSPACE_AND_SDK.md` §§ Scenario lifecycle, Feature cache and `04_SERVICE_API_AND_RESULTS.md` §§ Staged API, Deterministic evaluation.

The network service's one-request `/planning/workflow/run` route can run a scenario dictionary, but it does not manage local projects. Uploading shared antenna or metric files from `workspace/antennas` or `workspace/metrics` affects only the active server scenario and invalidates downstream planning state. See `02_WORKSPACE_AND_SDK.md` § Shared configuration libraries.

## Interpret results and revise

Inspect `quality_summary`, per-interface `quality`, `service` assignments, and enriched `result_edges`. The summary's `success` means a narrow rank-threshold condition; broader acceptance requires explicit objectives. If planning is revised, create a new project folder and retain the previous accepted result. The automated proposal, validation, authorization, and revision loop in `05_ASSISTANT_WORKFLOW.md` is a decision for future assistant SDK work, not a current command.
