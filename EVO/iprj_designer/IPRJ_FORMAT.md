# .iprj File Format Notes

Reverse-engineered from `EVO/dxf_iprj_excel_conv.py` and real files under
`sites/` (primary reference: `sites/Banks/banks.iprj`). Session 1
(2026-07-02) surveyed all 29 `sites/**/*.iprj` files and round-tripped every
one through `model/iprj_io.py`; findings below. Items still marked
**(open)** need the vendor software to settle.

## Container

XML, UTF-8. Two dialects exist in the wild:

**Vendor form** (23 of 29 site files) — root `Config` with `date`
(`YYYY_MM_DD_HH:MM:SS`) and `Version="1.1"` attributes, a
`<ProductInformation ProductCode="5220"/>` child, and **one
`<Configuration>` element per attribute** (~29 000 elements in a typical
2-sensor file — the vendor writes full placeholder arrays, see below):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Config date="2025_07_16_11:41:42" Version="1.1">
    <ProductInformation ProductCode="5220"/>
    <Configuration BackgroundImage="..."/>
    <Configuration Background_PosX="-244.00"/>
    ...
</Config>
```

**Converter form** (6 of 29) — root `IwarrSensorProject`, no root
attributes, no ProductInformation, a single `<Configuration>` element
carrying all attributes. These files (e.g. `Banks/sh-55 & banks_99.iprj`)
were produced by `dxf_iprj_excel_conv.py` and were used in the field, so the
vendor software accepts this form; several were later re-saved by the vendor
(same sites reappear in vendor form), confirming both dialects load.

`model/iprj_io.py` **reads both, always writes the vendor form** (that's the
form the vendor itself emits, so it is the safe canonical choice).

Values are strings; the vendor formats every float to exactly 2 decimals and
writes ints bare. Converter-form files carry arbitrary precision (e.g.
`MeterPerPixel="0.0762"`).

**Canonical origin (ROADMAP Item 11, `model/coords.normalize_origin`):**
`load_iprj` translates every coordinate in the project by
`(-Background_PosX, -Background_PosY)` so the background image's top-left
becomes world `(0,0)` — `Background_PosX/Y`, `MeterReference0/1_X/Y`, sensor
positions, event/ignore-zone points, ETA points, lineal endpoints, and
text-label positions all shift together as one rigid frame. This is a
**deliberate departure from vendor byte-fidelity**: `save_iprj` then writes
`Background_PosX = Background_PosY = 0` and every other coordinate shifted
accordingly, not the vendor's original arbitrary values. Distances and
calibration (`MeterPerPixel`/`ReferenceLength`, translation-invariant) are
unaffected — only the load→save round-trip contract for absolute position
changes. See `tests/test_coords.py` and `tests/test_roundtrip.py`
(`test_attribute_roundtrip` asserts the shifted-not-identical contract).

**Placeholder arrays:** the vendor always writes fixed-size arrays with
disabled entries — per sensor 64 EventZones × 10 Conditions each and 10
IgnoreZones, plus 100 Lineals and 100 Textlabels — with `Enable="0"` and
zeroed fields. Indices are 0-based and contiguous in every surveyed file.
Converter-form files write only the entries they use.

**Multi-sensor 2-file split (ROADMAP Item 9, `model/multifile.py`):** the
vendor caps a single file at 2 sensors, so a 3-4 sensor project is written
as a **pair of files** — `<base>_1_2.iprj` (sensors 1-2) and
`<base>_3_4.iprj` (sensors 3-4, serialized as `Radarsensor_0/1` in that
file — the sensor *index* restarts, but `OutputNumber` is preserved
byte-for-byte; those are project-wide detector-rack channels, not a
per-file concept). Both files are otherwise **100% vendor-clean single
.iprj files** — there is no in-file marker connecting them, only the
filename convention, so either one opens standalone in the vendor
software without choking on an unrecognized attribute.

Ownership on the split (ROADMAP Item 21, `model/bands.py`): `Lineals_*` and
`Textlabel_*` are routed by **index band** rather than all living in the
`_1_2` file. Each 100-slot array is divided into indices **0–19** (GENERAL),
**20–59** (FILE1 — sensors 1&2) and **60–99** (FILE2 — sensors 3&4). The
`_1_2` file carries GENERAL + FILE1 (FILE2 band blanked); the `_3_4` file
carries GENERAL + FILE2 (FILE1 band blanked). The **GENERAL band is
duplicated into both files**, so notes/centerlines placed there — or
auto-written by the vendor, which fills the lowest free index — render in
both. `project.extra` (Zoomfaktor, plot prefs) still stays with the `_1_2`
file. Ownership carries **no on-disk tag**: it is inferred on load from the
band an element's slot index falls in and re-materialized into that band on
save (`model/centerline.py`, `model/labels.py`). A multi-segment centerline
stays wholly within one band; a band with no room for an element overflows
(the writer returns it, the GUI warns) rather than spilling past the vendor's
fixed 100 slots. This realizes the ITEM9_SPLIT_PLAN.md §8
per-sensor-lineal-range idea; the `_3_4` file now renders its sensor-specific
guides standalone, not just the shared general ones.

Pairing relies on Item 11's origin normalization above: because both
files share the same background image and both are independently
normalized to `Background_PosX/Y = (0,0)`, "relative to top-left" is a
common frame and the merge is a sensor-list append plus a per-band recombine
of the annotation arrays (GENERAL + FILE1 from the `_1_2` file, FILE2 from the
`_3_4` file; the primary's GENERAL block wins) — no cross-file coordinate
delta is ever computed. `check_background_match` verifies this premise on the
overlay-open path (where a user picks two arbitrary files): image dimensions,
post-normalization position, scale, rotation, and effective meters-per-pixel
must all agree (hard fail if not); a pixel-content hash mismatch on
otherwise-matching geometry is a soft warning the GUI confirms rather than
blocks. `general_blocks_match` is a parallel soft-warn on the annotations: if
the two files' GENERAL bands disagree (one edited independently), the GUI can
flag that the primary's copy will win.

## Attribute namespace (flat, underscore-indexed)

`{i}`, `{j}`, `{k}` are 0-based integer indices.

### Background & calibration

| Key | Meaning |
|---|---|
| `BackgroundImage` | base64-encoded PNG (all 29 surveyed files embed PNG) |
| `Background_PosX`, `Background_PosY` | world position of the image top-left (px units, can be negative) |
| `BackgroundImageRotation` | degrees; `-90.00` seen in two converter-era Banks files. Rotation semantics (pivot point) **(open)** |
| `BackgroundImageScale` | percent; `100` everywhere except `94` in the same two rotated files |
| `Zoomfaktor` | vendor-only viewer zoom (e.g. `1.30`); pure display preference |
| `MeterPerPixel` | the operative scale factor — but vendor files round it to **2 decimals** |
| `ReferenceLength` | real distance in **meters** between the two reference points |
| `MeterReference0_X/Y`, `MeterReference1_X/Y` | two reference points in world px |

Two converter-written files spell the scale key **`MetersPerPixel`** (with
s); `sh-55 & banks_evo.iprj` has that key and no ReferenceLength/references
at all. The loader accepts both spellings and remembers which it saw
(`Background.meter_per_pixel_key`).

**Calibration precision (Session 1 finding):** the vendor's 2-decimal float
formatting clobbers `MeterPerPixel` (Banks stores `0.08` where the true
scale is `0.0762` — a 5 % error if trusted), but the reference pair +
`ReferenceLength` carry full precision and imply the true value:
`MeterPerPixel ≈ ReferenceLength / pixel_distance(Ref0, Ref1)` holds to
within the 2-decimal rounding in every vendor file. So **the reference pair
is the authoritative calibration**; `model/units.effective_meter_per_pixel`
re-derives from it. One counterexample guides the fallback: `ex27bg2.iprj`
has `ReferenceLength` edited (3.05 m) without re-applying calibration, so
its implied value (0.066) disagrees with stored (0.22) far beyond rounding —
when pair and stored value disagree beyond rounding, trust the stored value.

The format natively stores the same "two points, known distance" calibration
the GUI will offer; the "known image width" method is expressed as a
two-point calibration across the image's top edge (`units.calibrate_image_width`).

### Coordinate system (confirmed in Session 1)

- Zone points, sensor positions, reference points share one world coordinate
  space in **pixel units**, y-down (image convention).
- The background image is placed with its top-left at
  `(Background_PosX, Background_PosY)`; coordinates are not clamped to the
  image (negatives appear in real files; ignore zones commonly sprawl far
  outside it).
- Real-world distance = pixel distance × effective meters-per-pixel (above).
- Confirmed visually with `scripts/overlay_zones.py` on `Banks/banks.iprj`
  and `86_US95&SH8/us95&sh8.iprj`: zones land precisely on the lanes,
  sensors at their mounting corners, at `BackgroundImageScale=100` and
  rotation 0 the image spans exactly (PosX..PosX+width, PosY..PosY+height).

### Sensors

`Radarsensor_nrOfSensors`, then per sensor `Radarsensor_{i}_…`:

`Position_X`, `Position_Y`, `AzimuthAngle`, `ElevationAngle`,
`RoadGradientAngle`, `InstallationHeight`, `RainInterferenceThreshold`,
`HighwayMode`, `MaxStopTime`, `FrequencyChannel`, `Gps_lat`, `Gps_lng`

> **Recording overlay alignment (Item 36).** `Position_X/Y` (world pixels) are
> the map anchors the EVO-recording overlay aligns to. An EVO recording's `C;`
> line reports every sensor's position in the *EVO frame* (metres) — groups of
> three `x,y,confidence` per sensor slot 0-3, absent sensors written `?`, then a
> trailing `longitude,latitude,apikey`. With ≥2 sensors present in both, the
> overlay fits a 2D similarity (rotation + scale + translation) from these
> correspondences (`model/replay.build_align_transform`); the EVO frame is
> rotated a site-dependent amount from the map (≈27° at Banks), so a single-
> anchor translation is not enough. `AzimuthAngle` (sensor boresight heading) is
> *not* currently used for alignment — the multi-sensor fit supersedes it — but
> is the likely lever for a future single-sensor orientation recovery.

### Event zones (the loops)

`Radarsensor_{i}_EventZone_{j}_…`:

| Key | Meaning |
|---|---|
| `Enable` | 0/1 |
| `ZoneName` | free text, e.g. `"PH 4 SB inside"`. The `"{index+1}: "` prefix is a **converter artifact**, not a vendor rule — only 172 of 2544 surveyed zones (all in converter-written files) carry it; vendor-authored names are plain |
| `NrOfZonePoints` | vertex count (4 for rectangles; up to 10 seen). Matches the actual `ZonePoint` count in all 29 files, so `iprj_io` derives it from the point list on save |
| `ZoneType` | integer enum, vendor-UI names confirmed 2026-07-03 (Phase 2): `0` **Motion**, `1` **Presence**, `2` **Sidewalk** (`model/domain.ZoneType`). Consistent with the survey: stop-bar zones ("SB…") are type 1 because stop-bar detection is presence detection; advance/count zones and all placeholders are 0. Sidewalk zones take no conditions |
| `PhaseNumber` | signal phase (0–8 observed) |
| `OutputNumber` | detector output channel (maps 1:1 to the controller input it drives — this software numbers by output only); 0 and 17–64 observed across files |
| `EventMessageDelay`, `EventMessageExtend` | timing, integers |
| `EtaEnable`, `EtaPoint_X`, `EtaPoint_Y` | ETA feature |
| `ZonePoint_{k}_X`, `ZonePoint_{k}_Y` | polygon vertices, world px |

Vendor attribute order within a zone: Enable, ZoneName, NrOfZonePoints,
ZoneType, PhaseNumber, EventMessageDelay, EventMessageExtend, OutputNumber,
EtaEnable, EtaPoint_X/Y, ZonePoint_{k}_X/Y…, then the Conditions.
(`save_iprj` mirrors this order file-wide.)

### Conditions (nested per event zone)

`Radarsensor_{i}_EventZone_{j}_Condition_{k}_…`:

`Enable`, `OutputNumber`, `ConditionClass`, `Direction`, `VelocityMin/Max`,
`QueuelengthMin/Max`, `EtaMin/Max`, `EventMessageDelay/Extend`,
`NrCarsMin/Max`, `NrSmallTrucksMin/Max`, `NrBigTrucksMin/Max`,
`NrPedestMin/Max`

**Units (Session 4 finding):** condition values are metric. The enabled
speed conditions in the wild (`Franklin_KCID/…with speed.iprj` and the
Banks family) store `VelocityMin="40.23"` — exactly 25 mph in **km/h** —
and `QueuelengthMax="3047.70"` — exactly 9999 ft in **meters**. Enabled
conditions use wide-open sentinels for the un-filtered bounds:
`VelocityMax="16091.79"` (≈9999 mph), `QueuelengthMax="3047.70"`,
`EtaMax="999.00"`, and `Nr…Max="255"`; the designer writes the same
sentinels for new conditions (`model/domain.default_condition`) and edits
velocities in mph via `units.mph_to_kmh/kmh_to_mph`. The vendor UI shows
speed bounds as min 0 / max 9999 (mph).

**Semantics (resolved 2026-07-03, Phase 2 — vendor software consulted;
codes in `model/domain.py`):** there is no per-type condition schema on
disk — every condition is written with the full attribute set, and which
fields are meaningful follows from the owning zone's `ZoneType`:

- **Presence (1)**: output, delay, extend, `Queuelength…`, and the
  per-class `Nr…` vehicle-count filters.
- **Motion (0)**: `ConditionClass`, `Direction`, delay, extend,
  `Velocity…`, `Eta…` (plus output — the enabled speed conditions in the
  wild all carry a real `OutputNumber`).
- **Sidewalk (2)**: no conditions at all.

`ConditionClass` is the **vehicle-class filter** of a Motion condition, not
a condition-type discriminator: `0` all, `1` car, `2` bike/ped, `3` small
truck, `4` big truck, `5` car + big truck, `6` car + small truck, `7` car +
small + big truck (the `0` on the real speed conditions = "all classes").
`Direction` is relative to the sensor: `0` both directions, `1`
approaching, `2` receding.

### Ignore zones

`Radarsensor_{i}_IgnoreZone_{j}_…`: `Enable`, `IgnoreEverything`, `ZoneName`,
`NrOfZonePoints`, `ZonePoint_{k}_X/Y`

Survey of the enabled ignore zones in the wild (48 across the site files):
38 have `IgnoreEverything="1"`, 10 have `0`; every disabled placeholder is
`0`. `model/domain.new_ignore_zone` defaults to `1` accordingly. What
exactly a `0` zone still ignores **(open — needs vendor software)**.

### Annotations

- `Lineals_{i}_…`: `Enable`, `Point_0_X/Y`, `Point_1_X/Y`
- `Textlabel_{i}_…`: `Enable`, `Text`, `Position_X/Y`, `FontSize`, `FontBold`,
  `FontUnderline`, `FontItalic`, `RotationAngle`, `Textcolor_Red/Green/Blue`

Both arrays are the vendor's fixed 100 slots (`{i}` 0–99). Vendor software
keys these **by index** — writing slot 10 with 1–9 absent reloads and
re-saves as slot 10 — and auto-writes new entries to the lowest free index.
The designer exploits that: the slot index band carries file ownership on the
2-file split (see "Multi-sensor 2-file split" above and `model/bands.py`).
Disabled `Textlabel` slots park off-canvas at `Position_X/Y = -9999.00` (not
`(0,0)`); disabled `Lineals` slots zero their points. A real enabled text
label is `FontSize="12"` with `RotationAngle` in **degrees** (`90.00` seen)
and `Textcolor_*` in 0–255 RGB; the designer creates new labels white
(`255/255/255`), size 12, no bold/italic/underline, rotation 0.

**Centerline encoding (ours, Session 7.3 — `model/centerline.py`):** the
format has no polyline entity, so the designer's approach centerlines
(typically several per project — two intersecting roads at minimum) are
each stored as a chain of enabled `Lineal`s, one per segment, `Point_0` at
the lower station (segment *i* runs point *i* → *i+1*; `Point_0` of the
first segment is station 0, the stop bar). On load the ordered polylines
are reconstructed by walking enabled Lineals as an undirected graph:
every connected component that forms a simple open chain of **two or more
segments** is one centerline (shared vertices matched at the vendor's
2-decimal precision); station 0 is the chain end written as its terminal
segment's `Point_0`.

*Identification rule and its edges:* `Lineal` carries no name or tag, so
centerlines are identified purely by shape — a Lineal that shares an
endpoint with another Lineal is part of a centerline. Consequences:

- A *lone* segment is taken to be a stray vendor-drawn reference line,
  never a centerline; it is ignored on load and left untouched on save.
  So that a genuine single-segment (straight) centerline survives, save
  splits it at its midpoint into two collinear Lineals — it reloads with
  one interpolated mid vertex, geometrically identical.
- Intersecting roads are fine: centerlines that *cross mid-segment* share
  no endpoint and stay separate. But two centerlines drawn with a
  coincident *vertex* would merge (or, if the join makes a branch, stop
  being recognized) on reload — don't snap centerline vertices together.
- Components with branching vertices or cycles are never centerline
  candidates and are left untouched by save.

**Centerline-name labels (ours, ROADMAP Item 22 — `model/labels.py`):** a
centerline's display name is likewise carried with no format extension — as a
**no-rotation `Textlabel` sitting at the centerline's far end** (the vertex
furthest from the stop bar). Like the centerline chain and the zone/centerline
attachments, the link has no on-disk tag and is **re-derived on load by
geometry**: a no-rotation enabled label within a small tolerance (~0.05 world
px, `NAME_LABEL_TOL`) of a centerline's far end is adopted as that centerline's
name label, and its `Text` becomes the name (`match_name_labels`, one-to-one,
nearest-wins). The label lives in the same index band as its centerline, so a
sensor-owned centerline's name travels to the right file on the 2-file split.

**Centerline-membership labels (ours, ROADMAP Item 26 — `model/labels.py`):**
which zones belong to which approach centerline is likewise carried with no
format extension — as a second **no-rotation `Textlabel`** whose `Text` reads
`"[centerline name]: [sensor_zone slots]"` (e.g. `"N_CL: 2_5, 2_7, 3_1"`),
parked top-left (its position is cosmetic). Each member is named by its
**(sensor index, zone index) slot**, because the vendor stores zones in fixed
per-sensor slots that persist by index across a save/reload (`save_iprj` writes
every `EventZone_{zi}` slot verbatim, `load_iprj` restores it to the same
index — the same property `model/bands.py` relies on for Lineals/Textlabels).
The slot is therefore a *unique*, round-trip-stable identifier, unlike
`OutputNumber`, which real projects reuse across zones (e.g. count loops sharing
one output). On load the label is re-parsed (`parse_membership_label`) and each
listed slot re-attached by projecting the zone onto the datum — **no geometry
matching** — superseding the older geometric `derive_attachments`, which now
runs only for a file carrying no membership label at all.

The sensor index is written in **absolute (merged-project) space** (sensors
0–3). On the 2-file split the `_3_4` half's sensors are renumbered to 0/1, so on
load the reader offsets file-local indices back to absolute from the file's pair
role (`_derive_membership` / `Viewer._sensor_index_offset`): opening a bare
`_3_4` half (its sensor 0 = absolute sensor 2) still resolves its own members, a
slot for a sensor absent from the loaded file simply doesn't resolve, and the
merged overlay reads them straight through. The label sits in its centerline's
index band (so a sensor-owned group's membership travels to the right file), but
that routes only the *label*: a **zone's** file is still decided by which sensor
holds it (`split_project` partitions by sensor), because the vendor stores zones
in per-sensor arrays — membership is an organizational grouping, not a zone→file
override. A membership label is told apart from a plain/name label purely by its
`name: sensor_zone-list` text shape, so an ordinary label is never mistaken for
one.

### Plot preferences

`PlotPreferences_…`: `AdjustTrackToLane`, `HideBackgroundImage`, `HideClass`,
`HideRainInterferenceLevel`, `HideSensorBeam`, `ShowObjectID`, `ShowRadar`,
`ShowReference`

## Session 1 verification checklist (resolved 2026-07-02)

- [x] Round-trip every `sites/**/*.iprj` (parse → serialize → attribute-level
      diff) — 29/29 pass, `tests/test_roundtrip.py`
- [x] One-`<Configuration>`-per-attribute vs. single-element form; root tag —
      both dialects documented above; loader reads both, writer emits vendor form
- [x] Confirm pixel-space theory — confirmed via `scripts/overlay_zones.py`
      on Banks and US95&SH8 (see Coordinate system section)
- [x] `ZoneType` observed values (0/1/2 with name correlations), observed
      `OutputNumber` range (0, 17–64), `ZoneName` prefix shown to be a
      converter artifact — documented in the Event zones table
- [x] vendor-UI names for `ZoneType` values, `ConditionClass` and
      `Direction` codes, per-type condition-field relevance — resolved
      2026-07-03 from the vendor software (Phase 2); see the Event zones
      and Conditions sections and `model/domain.py`
- [ ] **(open)** which attributes are mandatory for the vendor software to
      load a file — untestable without the vendor software; mitigated by
      writing the vendor's own form with full placeholder arrays preserved
      on round-trip (from-scratch files write only real entries, which the
      accepted converter-form files show is tolerated)
- [ ] **(open)** `BackgroundImageRotation` pivot semantics (only two legacy
      files rotate; revisit if a rotated site ever needs editing)
