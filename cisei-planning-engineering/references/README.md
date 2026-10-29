# CISEI planning engineering-agent knowledge package

Snapshot baseline: 2026-09-24, with reviewed planning-model guidance consolidated on 2026-09-29.  
Repository base commit: `2a63fd5d7dc826915a19d3d5ac9e90b9fa66d464`  
Source state: working tree contains later, uncommitted planning SDK and service changes.

This is a dated knowledge package for an engineering assistant that helps the team understand the planning software and design the assistant SDK and MCP integration. It is not a live connection to the planning service. Proposed assistant behavior remains separate from implemented behavior.

Accepted review decisions are incorporated into the canonical references. `CISEI_Plugin_Review_Notes.md` is not part of the plugin knowledge set and is not required as an override.

## Reference index

1. `00_AGENT_INSTRUCTIONS.md` — behavior, evidence, and explanation rules.
2. `01_CURRENT_ARCHITECTURE.md` — implemented services and ownership.
3. `02_WORKSPACE_AND_SDK.md` — local workspace, sessions, lifecycle, cache, and revisions.
4. `03_SCENARIO_FORMAT.md` — scenario dictionary, TOML, CSV, routing/connectivity semantics, and validation.
5. `04_SERVICE_API_AND_RESULTS.md` — staged API, result/evaluation structure, and metric/rank interpretation.
6. `05_ASSISTANT_WORKFLOW.md` — proposed iterative planning and technology-dependent redesign workflow.
7. `06_DESIGN_GAPS_AND_DECISIONS.md` — confirmed decisions and unresolved work.
8. `07_CANONICAL_CASES.md` — current LTE, Wi-SUN, custom antenna/metric, fixed-rank, and hybrid-routing patterns.
9. `08_USAGE_GUIDE.md` — how to prepare and run a current SDK project.
10. `09_MCP_INTERFACE_REQUIREMENTS.md` — boundaries, contracts, and acceptance checks for creating an MCP interface.
11. `10_EXPLORATION_WORKFLOW.md` — reviewed seven-question guided exploration of the planning software.

The authoritative implementation sources used for this snapshot are:

- `client_sdk/src/cisei_planning_sdk/`
- `app/routes_planning.py`, `app/main.py`, `app/main_hub.py`, and `app/session.py`
- `app/feature_cache.py`
- `cisei_lib/planners/planning_scenario.py`
- `cisei_lib/planners/graph_planner.py`
- `cisei_lib/planners/planning_solution.py`
- `examples/`

Generated build folders, deleted files, `.Trash-0`, notebook checkpoints, and legacy planner files are not authoritative.

## Status vocabulary

- **Implemented** — behavior present in the authoritative source snapshot.
- **Decision** — direction chosen by the team, although implementation may be incomplete.
- **Proposal** — recommended design still open to revision.
- **Gap** — current code does not yet meet the intended workflow.

## Known verification boundary

The structured result/evaluation contract is documented. Exact public SDK helper names for reports, maps, and plots must still be verified against the current SDK/examples before being presented as implemented methods.

## Version warning

`client_sdk/pyproject.toml` declares version `0.1.18`, while `client_sdk/src/cisei_planning_sdk/__init__.py` currently reports `0.1.16`. The built/distributed package may therefore differ from a direct source import. Resolve this before using the version as a compatibility guarantee.
