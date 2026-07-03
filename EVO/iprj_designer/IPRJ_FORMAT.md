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

**Placeholder arrays:** the vendor always writes fixed-size arrays with
disabled entries — per sensor 64 EventZones × 10 Conditions each and 10
IgnoreZones, plus 100 Lineals and 100 Textlabels — with `Enable="0"` and
zeroed fields. Indices are 0-based and contiguous in every surveyed file.
Converter-form files write only the entries they use.

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

### Event zones (the loops)

`Radarsensor_{i}_EventZone_{j}_…`:

| Key | Meaning |
|---|---|
| `Enable` | 0/1 |
| `ZoneName` | free text, e.g. `"PH 4 SB inside"`. The `"{index+1}: "` prefix is a **converter artifact**, not a vendor rule — only 172 of 2544 surveyed zones (all in converter-written files) carry it; vendor-authored names are plain |
| `NrOfZonePoints` | vertex count (4 for rectangles; up to 10 seen). Matches the actual `ZonePoint` count in all 29 files, so `iprj_io` derives it from the point list on save |
| `ZoneType` | integer enum: `0`, `1`, `2` observed. `0` is the default (all placeholders; advance/count zones); `1` appears on stop-bar zones ("SB…") in vendor files; `2` only in one legacy converter file. Vendor-UI names for the values **(open — needs vendor software)** |
| `PhaseNumber` | signal phase (0–8 observed) |
| `OutputNumber` | detector output/input channel; 0 and 17–64 observed across files |
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
sentinels for new conditions (`gui/app.py new_condition`) and edits
velocities in mph via `units.mph_to_kmh/kmh_to_mph`. `ConditionClass`
vendor-UI meaning **(open — needs vendor software)**; `0` observed on the
real speed conditions.

### Ignore zones

`Radarsensor_{i}_IgnoreZone_{j}_…`: `Enable`, `IgnoreEverything`, `ZoneName`,
`NrOfZonePoints`, `ZonePoint_{k}_X/Y`

### Annotations

- `Lineals_{i}_…`: `Enable`, `Point_0_X/Y`, `Point_1_X/Y`
- `Textlabel_{i}_…`: `Enable`, `Text`, `Position_X/Y`, `FontSize`, `FontBold`,
  `FontUnderline`, `FontItalic`, `RotationAngle`, `Textcolor_Red/Green/Blue`

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
- [ ] **(open)** vendor-UI names for `ZoneType` values — needs vendor software
- [ ] **(open)** which attributes are mandatory for the vendor software to
      load a file — untestable without the vendor software; mitigated by
      writing the vendor's own form with full placeholder arrays preserved
      on round-trip (from-scratch files write only real entries, which the
      accepted converter-form files show is tolerated)
- [ ] **(open)** `BackgroundImageRotation` pivot semantics (only two legacy
      files rotate; revisit if a rotated site ever needs editing)
