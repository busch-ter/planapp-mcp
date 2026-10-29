# Requirements for creating the CISEI MCP interface

Status: design requirements and proposed surface, not implemented tools or routes. The snapshot contains a network-service HTTP API and Python planning SDK; it does not include a working MCP server. MCP supplies a tool/resource interface to an AI client and does not itself run the model or make planning judgments. Consult `01_CURRENT_ARCHITECTURE.md`, `04_SERVICE_API_AND_RESULTS.md`, and `05_ASSISTANT_WORKFLOW.md` before implementation.

## Boundary and placement

- **Decision:** the local assistant SDK owns workspace files, CSV normalization, deterministic validation, authorized project creation, revision retention, and planning SDK calls. The network service owns scenario interpretation, candidates, metric orchestration, solving, and deterministic evaluation. The features service owns geographic and propagation extraction. A shared AI/MCP component must not write user workspaces or require inbound access to individual Jupyter containers. Local components initiate outbound calls.
- **Proposal:** expose an MCP server from a shared service for read-only schema/catalogue discovery and remote validation/evaluation capabilities; let the local assistant SDK mediate all local file operations and user authorization. Decide explicitly whether the MCP client lives in the shared assistant service, the local Python environment, or both. Define the actual AI host, supported transport, deployment address, and trust boundary before coding. Do not expose host filesystem tools from the shared service.
- **Gap:** current hub token authentication is not real-user login, and the default features-worker prefix can collide across planning workers. Design account/session/project/worker identities separately. The MCP server must not equate an AI conversation ID with the network worker's `user_id` or use a model-supplied identifier as an authorization credential.

## Proposed MCP surface

These names are illustrative design candidates, not existing APIs. Publish stable input and output schemas before attaching them to a host.

| Capability | Candidate MCP form | Owner and effect |
| --- | --- | --- |
| Scenario schema and compatibility | Versioned resource or read tool | Shared service reads an authoritative schema snapshot derived from the canonical loader; no local I/O. |
| Built-in antenna and metric catalogue | Resource or read tool | Shared service exposes metadata; local SDK supplies workspace additions with explicit provenance. |
| Scenario validation | Tool | Delegate to network-service validation for a complete expanded scenario dictionary; return structured errors. No project is committed. |
| Planning evaluation | Tool or read resource keyed by an authorized result | Delegate deterministic checks to network service; accept structured exported results, objectives, and bounded relevant records. |
| Project proposal and revision | Structured AI response, not a privileged write tool | Assistant SDK validates the proposal, requests user authorization, serializes TOML, and writes a new local project. |

The MCP design should specify whether live network planning is exposed at all. If exposed, use the existing staged API or workflow through a controlled service client; declare cost/time bounds, idempotency, cancellation, feature-service dependencies, and result persistence. Do not claim the server can open a local `scenario.toml` path: the SDK must expand local CSV and send concrete data. Do not confuse a plugin instruction bundle with a deployed MCP integration; this release declares no `mcp.json` or live connection.

## Contract for each tool or resource

Specify a versioned name and description; strict JSON input/output schema; required and optional fields; units and CRS; size limits; result provenance; supported software/schema versions; and whether it has side effects. Keep scenario dictionaries separate from TOML files and `features.json` separate from `result.json`. Include objective thresholds when asking for acceptance or recommendations. The service does not currently publish a formal scenario JSON Schema, so produce and test one against `PlanningScenario.from_config_dict` before treating AI output as validated. See `03_SCENARIO_FORMAT.md` §§ Canonical representation, Current validation scope, Schema limitation.

Return stable machine errors with code, stage, field/path, entity, message, retryability, and optional suggestions; distinguish invalid input, version mismatch, authorization failure, transport/service outage, and planning-stage failure. Existing HTTP errors often have a text envelope, so define a compatible translation instead of pretending typed errors exist. Retry only recoverable failures with a bounded attempt count. The user receives domain questions and actionable terminal failures rather than raw traces. See `04_SERVICE_API_AND_RESULTS.md` § API work needed for AI correction.

## Security, isolation, and revision requirements

Bind each request to authenticated human/account and authorized workspace/project context. Enforce identity on the server, isolate conversations and planning workers, apply timeouts and bounded payloads, and avoid leaking local paths, private inputs, tokens, or one user's cache to another. Keep credentials outside tool arguments generated by the model. Record proposal IDs, parent revision, schema/software versions, assumptions, authorization, and resulting project identity; make accepted revisions immutable by writing a new project directory. These are requirements to design and implement, not claims about today's service. See `02_WORKSPACE_AND_SDK.md` § Revision policy and `06_DESIGN_GAPS_AND_DECISIONS.md` §§ Identity and sessions, Compatibility, Revision metadata and comparison.

## Implementation sequence and acceptance checks

1. Resolve SDK version mismatch; publish a versioned scenario schema and catalogue contract from current code. Verify valid and invalid LTE cell, Wi-SUN graph, custom antenna, and custom metric cases against the actual loader.
2. Define proposal, validation error, objective, evaluation, and revision envelopes. Map existing HTTP outcomes without changing the current planning SDK contract unexpectedly.
3. Build the local assistant SDK file and authorization workflow; manually test the complete loop before introducing MCP transport.
4. Implement MCP discovery and selected remote tools, configure host connection/auth, and test tool listing, schema validation, identity isolation, retryability, timeouts, and unavailable services.
5. Run end-to-end creation, execution, evaluation, and authorized revision. Confirm a failed or rejected proposal cannot overwrite a prior accepted project. Check that `success` is interpreted only against stated objectives.

The suggested order reflects `06_DESIGN_GAPS_AND_DECISIONS.md` § Suggested implementation order. Tool names, transport, host, endpoint mapping, authentication provider, version policy, and deployment topology remain open design decisions.
