# Guided exploration of CISEI Planning Engineering

This workflow explains the planning software from the planning problem through project review. It is a guided explanation, not a quiz. Start with **"Start the CISEI exploration workflow"**, ask any numbered question directly, or use "next" to advance.

Answer one question at a time. For structural concepts use **concept → smallest valid example → interpretation**. Prefer canonical `scenario.toml`, `nodes.csv`, SDK, and result fragments. Keep implemented behavior separate from accepted design decisions and future extensions. Do not imply that this plugin is connected to a live deployment.

## 1. Planning problem

1. **What does the CISEI planning software do?**  
   Start with connected/backhaul nodes and unconnected nodes, candidate links, feature extraction, and technology-specific link metrics. Explain that different link technologies may use different metrics. Introduce services and implementation architecture only after the planning problem is clear. Use `00_AGENT_INSTRUCTIONS.md` and `01_CURRENT_ARCHITECTURE.md`.

## 2. Workspace and project inputs

2. **How is the workspace organized, and where are the inputs to a planning project defined?**  
   Explain the purpose of `antennas/`, `metrics/`, `data/`, `notebooks/`, and `projects/`. State the minimum project files: `scenario.toml`, plus `nodes.csv` when referenced by `[instances]`; embedded `sites` may make TOML the sole project input. Explain that `features.json` and `result.json` are lifecycle artifacts, not first-run prerequisites. Use `02_WORKSPACE_AND_SDK.md`.

## 3. Templates and instances

3. **How do antenna, interface, and device templates become concrete planning nodes?**  
   Lead with `antenna → interface → device template → concrete instance`. Show a minimal TOML fragment and one CSV row using `device_profile`, then explain exactly what is instantiated. Introduce embedded concrete `sites` only after the template/CSV model is clear. Explain the accepted mounting-height model and distinguish current implementation from target design where necessary. Use `03_SCENARIO_FORMAT.md` and `07_CANONICAL_CASES.md`.

## 4. Minimum scenario and network semantics

4. **What is the minimum `scenario.toml` needed to define a planning scenario, and what do its antenna, interface, device, metric, and connectivity sections mean?**  
   Use short separate TOML fragments. Explain fixed/connected devices and initial rank, including fiber roots with `rank = 0.0`; distinguish interface `can_relay` from device `can_route`; and distinguish routing capability from candidate connectivity rules. Explain that the minimum is planner-dependent: graph/Wi-SUN normally exposes connectivity rules, while cell/LTE can generate primary candidates without generic `net.connectivity`. Use `03_SCENARIO_FORMAT.md` and `07_CANONICAL_CASES.md`.

## 5. Candidate links, features, and metrics

5. **How are candidate edges defined, how are features extracted for those candidates, and how are those features converted into link metrics?**  
   Explain the sequence `candidate edge → raw features → technology-specific metric`. Describe graph connectivity rules versus cell-generated candidates, feature-cache reuse, and the mapping from interface `tech` to `[metrics.<tech>]`. Distinguish built-in metric specs from user metric TOML files in the workspace and explain scenario-local upload. Do not move into solving yet. Use `02_WORKSPACE_AND_SDK.md`, `03_SCENARIO_FORMAT.md`, and `04_SERVICE_API_AND_RESULTS.md`.

## 6. Session, solve, evaluation, and persistence

6. **How is a project opened as a planning session, how is the evaluated graph solved, and how are the result and evaluation persisted?**  
   Explain `PlanningClient`, `PlanningProject`, `open_project`, and `ScenarioSession`; then `solve`, `evaluate`, and `save_result`. Make the distinction explicit: **metric = quality/cost of one candidate link; rank = accumulated quality/cost of the path to the backhaul**. Explain `rank_threshold`, quality classifications, `features.json` versus `result.json`, and durable workspace state versus ephemeral worker/session state. Candidate construction and metric computation should be referenced as prior stages, not re-taught. Use `02_WORKSPACE_AND_SDK.md` and `04_SERVICE_API_AND_RESULTS.md`.

## 7. Reports, visualization, and project revision

7. **What reports and visualizations are available from a planning result, and how should the user revise a project when the evaluation shows poor or unserved nodes?**  
   Enumerate only report/visualization helpers verified in the current SDK/examples; do not invent method names. Structured evaluation/result data is the source of truth and plots are interpretation aids. Explain that `poor` or `unserved` nodes under the chosen `rank_threshold` trigger project review. LTE revisions may include a valid new tower/site, sector changes, parameter changes, or a hybrid second interface using another technology on strategically connected nodes. Wi-SUN/mesh revisions may add relay-only infrastructure nodes that are not meters. After connectivity-changing revisions, rebuild candidates, recompute affected metrics, solve, and evaluate again. Current remediation is user/assistant-driven; automatic infrastructure/relay extension is a future planner capability. Accepted redesigns become new project revisions rather than overwriting the previous one. Use `04_SERVICE_API_AND_RESULTS.md`, `05_ASSISTANT_WORKFLOW.md`, `06_DESIGN_GAPS_AND_DECISIONS.md`, and `07_CANONICAL_CASES.md`.

After question 7, the planning-software exploration is complete. If the user wants to design the assistant SDK or MCP interface next, switch to `05_ASSISTANT_WORKFLOW.md`, `06_DESIGN_GAPS_AND_DECISIONS.md`, and `09_MCP_INTERFACE_REQUIREMENTS.md` rather than extending this guided sequence with unreviewed questions.
