# Scenario, TOML, and site CSV format

## Canonical representation

The canonical in-memory/API representation is a Python/JSON-compatible scenario
dictionary. TOML is a local serialization of that dictionary. Both server-side
TOML loading and API loading ultimately call `PlanningScenario.from_config_dict`.

The planning SDK loads `scenario.toml`, reads a referenced CSV locally, expands
it into concrete `sites`, removes the file-based `instances` section, and sends
the complete dictionary to the network service. A remote service therefore does
not need access to the local TOML or CSV path.


## Template and instance model

The primary model is:

`antenna profile → interface profile → device template → concrete instance`

An interface references one antenna through `antenna_id`. A device template groups
one or more interface profiles through `interfaces`. With external instances, each
`nodes.csv` row chooses a device template through `device_profile`; the SDK then
instantiates the device, its interfaces, and their referenced antennas at that
physical site. Embedded concrete `sites` are an alternative, richer representation
and should be introduced after this template/CSV model.

## Top-level sections

### `scenario`

Optional. `working_crs` identifies the projected coordinate reference system,
for example `EPSG:31982`. Distance-based planning requires usable projected
positions or a CRS from which positions can be resolved.

### `antennas.<profile_id>`

Reusable scenario antenna profiles. Recognized fields are:

- `kind` — defaults to `omni`;
- `model_id` — optional ID in an uploaded or built-in antenna library;
- `description`;
- `gain_dbi` — defaults to 0;
- `height_m` — **Implemented:** currently recognized and defaults to 7;
- `azimuth_deg`, `downtilt_deg`, and `beamwidth_deg`;
- `shadow_azimuth_deg`, `shadow_width_deg`, and `shadow_loss_db`.

Additional fields are preserved as metadata. Interfaces reference these
profiles through `antenna_id`.


### Installation-parameter design

**Decision:** installation height belongs to the installed device/site, not to the
reusable antenna model. A device template may provide a default `mount_height_m`; a
concrete site/device instance supplies the actual `mount_height_m` and overrides the
template default. Antenna `height_m` should therefore be deprecated/removed from the
target schema even though the current implementation still recognizes it.

Current limitation: mounting height belongs to the device, so all interfaces on one
concrete device inherit the same height. Different physical elevations currently
require separate devices; a future schema may move installation height to concrete
interfaces. Flat CSV remains appropriate for scalar instance properties such as
`mount_height_m`, while hierarchical per-interface/per-antenna installation settings
fit the embedded TOML/structured-site representation better.

**Decision:** when orientation follows the selected link geometry, `azimuth_deg`
should normally be planner-derived. `downtilt_deg` may likewise be derived where link
geometry determines it. Fixed physical sectors or other constrained installations
still require explicit orientation/tilt values or constraints.

### `interfaces.<profile_id>`

Required fields:

- `tech`;
- `freq_mhz`;
- `tx_power_dbm`;
- `antenna_id`.

Optional fields include `can_relay`, `max_links`, and `medium` (normally `rf`).
A profile must reference an existing scenario antenna profile.

### `devices.<profile_id>`

Required field:

- `interfaces` — a non-empty list of interface profile IDs.

Optional fields include `kind`, `connected`, `can_route`, `rank`, and
`mount_height_m`. Connected/root devices normally use finite rank 0; unconnected
devices normally begin with infinite rank.

### `metrics.<tech>`

Maps an interface technology to its metric specification. Current forms include
a built-in resource reference such as `{spec = "default"}` or
`{spec = "lte_tower_node"}`, an inline metric specification, or a specification
uploaded from one local TOML file. The technology key must correspond to the
`tech` used by interfaces.

### `instances`

Describes an external CSV. Supported SDK fields are:

- `source` — required, resolved relative to `scenario.toml`;
- `format` — only `csv` is supported, and it is the default;
- `profile_column` — defaults to `device_profile`.

The executable CSV accepts site identity from the first present value among
`site_id`, `position_id`, `id`, and `name`. It needs either `lat`/`lon` or
`x`/`y` for useful positioning. It can include:

- the configured device-profile column;
- `kind`;
- `mount_height_m`, `ant_h`, or `antenna_height_m`;
- `connected`, `can_route`, and `rank`;
- additional columns, which are retained as site metadata.

The device-profile value must name a profile in `devices`. The SDK creates one
concrete device and all interfaces listed by that device profile. Generated IDs
follow `<site_id>:d0` and `<site_id>:d0:i<index>`.

### `net.connectivity`

An array of automatic candidate-generation rules. Common fields are:

- `kind`: usually `rf` or `internal`;
- `tech`: required for RF selection;
- `source` and `destination`: selectors such as `connected`, `unconnected`,
  `relay`, `non_relay`, or `any`;
- `degree`: optional nearest-neighbor count;
- `limit`: optional maximum distance in metres.

### `net.candidate_edges`

An optional array of manual edges. Each entry requires `src` and `dst` concrete
interface IDs. Other fields become edge attributes.

### `sites`

An optional array of fully embedded concrete sites. Each site requires
`site_id`, normally has `kind`, and uses `lat`/`lon` or `x`/`y`. A site may
contain arrays of concrete devices and interfaces.

A concrete device requires `device_id` and `site_id`; it may include
`connected`, `can_route`, `rank`, and `mount_height_m`.

A concrete interface requires `interface_id`, `device_id`, `tech`, `freq_mhz`,
`tx_power_dbm`, and `antenna_id`; it may include `site_id`, `can_relay`,
`medium`, and `max_links`.


## Fixed nodes, routing, and connectivity semantics

A device with `connected = true` is already attached to the backhaul and is fixed
from the planner's point of view. Its initial `rank` represents the accumulated
quality/cost of that already-existing upstream path. A directly fiber-connected root
may use `rank = 0.0`; another connected device may use a finite non-zero rank when its
existing upstream path is known but not ideal. Unconnected devices normally begin
without a finite rank and receive rank through planning.

Routing has two levels and the flags must not be collapsed:

- `interfaces.<id>.can_relay` controls whether that interface may relay traffic for
  its technology; this is the natural model for a single-interface mesh such as
  Wi-SUN.
- `devices.<id>.can_route` controls forwarding between interfaces on a device and is
  important for multi-interface/cross-technology routing.

Connectivity is separate from routing. `net.connectivity` decides which compatible
interfaces may become candidate neighbors; routing flags decide whether traffic may
be forwarded through an interface/device after links exist. For example:

```toml
[[net.connectivity]]
kind = "rf"
tech = "wisun"
source = "relay"
destination = "any"
degree = 3
limit = 3000
```

The exact minimum scenario is planner-dependent. A graph/Wi-SUN scenario normally
needs explicit connectivity rules; the cell/LTE planner can generate its own primary
tower-to-client candidates and therefore may not need generic `net.connectivity`.

## Intake CSV versus executable CSV

**Decision:** the end user may initially provide a minimal raw CSV in
`workspace/data` containing site name, coordinates, and mounting height.

**Gap:** that raw file is not yet directly executable because the current SDK
also needs a device-profile assignment for every row. The future assistant SDK
must validate and normalize the intake file, ask which templates apply, and
write a project `nodes.csv` containing the selected `device_profile` values.

## Current validation scope

Scenario construction enforces required profile fields and basic numeric
conversion. `PlanningScenario.validate()` checks:

- interface profile to antenna profile references;
- device profile to interface profile references;
- concrete interface to antenna profile references;
- manual candidate endpoints against concrete interface IDs.

Planner construction, candidate generation, antenna-model lookup, metric
compilation, and metric computation can raise additional errors. An empty
`validation_errors` list does not prove that every later planning stage will
succeed.

## Schema limitation

**Gap:** this contract is implemented with Python constructors and runtime
validation; the service does not currently publish a formal JSON Schema. The
future integration should generate or maintain a versioned machine-readable
schema and test it against the same scenario loader.

