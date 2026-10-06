# Canonical planning cases

These cases summarize the active distributed examples. They demonstrate valid
combinations but do not replace the scenario contract or runtime validation.


## Minimal template-to-instance example

Use this pattern when teaching the scenario structure:

```toml
[antennas.node_omni]
kind = "omni"
gain_dbi = 6.0

[interfaces.wisun]
tech = "wisun"
freq_mhz = 915.0
tx_power_dbm = 30.0
antenna_id = "node_omni"
can_relay = true

[devices.wisun_router]
connected = false
interfaces = ["wisun"]

[instances]
source = "nodes.csv"
profile_column = "device_profile"
```

A CSV row that assigns `device_profile=wisun_router` creates one concrete device, its
`wisun` interface, and that interface's `node_omni` antenna at the row's position.

## Basic LTE cell planning

Source project: `examples/projects/example1_LTE_planning_basic`.

The scenario defines three 120-degree sector antenna profiles at azimuths 0,
120, and 240 degrees, plus an omnidirectional client antenna. Four LTE interface
profiles reference those antennas at 915 MHz. Tower device profiles contain two
or three sector interfaces; the client device profile contains one
non-relaying interface.

Connected towers have rank 0. Client sites are unconnected and cannot route.
The LTE metric refers to the built-in `lte_tower_node` specification. Site
instances come from `nodes.csv` through its `device_profile` column. The cell
planner builds primary candidates, so this example does not require a generic
`net.connectivity` rule.

## Single-radio Wi-SUN mesh

Source project: `examples/projects/graph_planner_wisun`.

The scenario defines gateway and node omnidirectional antennas and three
single-interface device profiles:

- gateway: connected, routing-capable, rank 0;
- router: unconnected, routing-capable, relay-capable interface;
- leaf: unconnected, cannot route, non-relaying interface.

All interfaces use technology `wisun` at 915 MHz. The metric refers to the
built-in `default` specification. One RF connectivity rule selects relay
sources and any destination, limits candidates to three neighbors, and limits
distance to 3000 metres. The example assigns `woodland` and `deneka` as leaves.

This case demonstrates mesh planning rather than LTE cell planning. A site is a
gateway because its device profile is connected/root-capable; a plot marker or
site name does not establish that role.


## Fixed-rank and hybrid-routing interpretation

A connected root with a direct fiber path can be modeled with `rank = 0.0`. A
connected node with an existing but non-ideal upstream path can start with a finite
non-zero rank; downstream planned ranks accumulate from that value.

A hybrid LTE/local-radio design should be explained as a multi-interface routing
case: LTE may connect strategically placed devices to the backhaul while another
technology reaches nearby devices. A poor LTE endpoint does not automatically imply
that a new LTE tower is the best revision.

For Wi-SUN/mesh projects, relay-only nodes are valid planning infrastructure even
when they are not meters. After adding a tower/sector/interface/relay that changes
connectivity, rebuild relevant candidates, recompute affected metrics, solve, and
evaluate again.

## Custom antenna library

Source: `examples/antennas/custom_omni.yaml`.

The example is a version-1 YAML document with an `antennas` list. Its one model
has:

- ID `custom_omni`;
- type `omni`;
- a human-readable model description;
- supported frequency range 902–928 MHz;
- a 915 MHz pattern with maximum gain 6 dBi.

The SDK reads the complete document and uploads it to an active scenario. A
scenario antenna profile can then select the model through `model_id`. The
upload is scenario-local and in memory.

## Custom metric

Sources: `examples/metrics/custom_metric.toml` and
`examples/metrics/gain_aware_metric.toml`.

Each file declares one version-1 metric, names `metric` as its result, and
defines the expression under `expressions.metric`. The basic demonstration uses
distance in metres. The gain-aware demonstration also reads transmitter and
receiver antenna gain. These formulas are demonstrations, not calibrated RF
models.

The SDK validates that the local file parses as TOML, then sends its text as the
scenario metric specification for one technology. Compilation and execution
occur in the network service.

## Embedded-site scenario editing

The advanced distributed notebook demonstrates a different representation:
the SDK opens an existing project, retrieves the expanded scenario from the
server, modifies the returned dictionary by adding a concrete site, and saves
that dictionary locally as TOML. An exported scenario includes embedded sites;
it does not include candidate edges, metrics, solution, or evaluation.

This pattern is useful for programmatic editing. For assistant generation, the
preferred exchange is likewise a structured scenario dictionary, followed by
validation and deterministic TOML serialization.

## What examples do not establish

Examples do not define supported technologies globally, prove that a metric is
appropriate, define business acceptance, or guarantee that every valid schema
combination can be solved. The engineering assistant must use the current
schema, catalogues, validator, and planning objectives together.

