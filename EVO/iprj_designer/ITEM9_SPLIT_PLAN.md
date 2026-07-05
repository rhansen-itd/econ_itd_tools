# Item 9 — Multi-Sensor 2-File Split: Architecture Plan

Opus planning output per [[ROADMAP.md]] Item 9. Fable (model split/merge/
validation) and Sonnet (File-menu + save wiring) implement this once the plan
lands. It resolves the three "Decide…" scope boxes on Item 9: the **pairing
model**, the **background-match check**, and the **save-path restriction**.

Read before starting: [[model/iprj_io.py]] (`Project`/`Sensor`/`Background`
dataclasses, `load_iprj`/`save_iprj`, `iprj_attributes`), [[model/units.py]]
(`effective_meter_per_pixel`, `background_image_size`,
`decode_background_image`), and [[gui/app.py]]'s `Viewer.__init__`,
`open_project`, `do_save`/`save`/`save_as`, `open_existing`, `add_sensor`.

**No Item-3 dependency.** The earlier "zone duplication across sensors on
load" concern (Item 3) turned out to be a property of the source files
themselves, not a loader bug — the load path associates zones with sensors
correctly. So the split/merge here can build directly on `load_iprj`/
`save_iprj` as they stand; the round-trip tests below still pin that
association, but nothing needs fixing first.

---

## 1. The one load-bearing invariant

**In memory there is exactly one `Project` with up to four sensors. The
editor, undo, drawing, templates, and centerlines are all unchanged.** The
"two files" only exist at the I/O boundary: a *split* on save and a *merge* on
overlay-open. Nothing in `gui/drawing.py`, `model/geometry.py`,
`model/templates.py`, or the toolbar changes.

Rejected alternative: keeping two live `Project` objects in sync. It would
duplicate the background, fork undo, and force every mutation to pick a
"current file." The flat 4-sensor list the app already has is strictly
simpler and the split is trivially derivable from it.

Consequences:
- The vendor cap of 2 sensors/file × 2 files = **4 sensors is the hard model
  cap.** `add_sensor` must refuse a 5th (see §5).
- All the multi-file logic is new pure-python in **`model/multifile.py`** plus
  a little Path/menu bookkeeping in `gui/app.py`. `model/iprj_io.py` stays a
  single-file XML codec and is not touched.

---

## 2. Decision — pairing model

**Filename convention only. No in-file marker.** Two files form a pair when,
in the same directory, their stems are identical except for a trailing
`_1_2` vs `_3_4`:

```
<base>_1_2.iprj   # sensors 1–2  (Radarsensor_0, Radarsensor_1)
<base>_3_4.iprj   # sensors 3–4, written as Radarsensor_0/1 in this file
```

Why not an in-file marker (an `extra` key cross-referencing the sibling):
each output file must stay **100 % vendor-clean** so the vendor software opens
it without choking on an unknown `<Configuration>` attribute. The filename is
the only channel that survives a vendor round-trip untouched.

**In-memory bookkeeping.** Add one field to `Viewer`:

```python
self.pair: tuple[Path, Path] | None = None   # (path_1_2, path_3_4)
```

- `None` for an ordinary single-file project (≤2 sensors, today's behavior).
- Set to the two source paths when a project spans two files — either because
  it was opened via overlay (§merge) or saved via the multi-file Save-As.

`Viewer.source` keeps its current meaning (the primary/`_1_2` path) so the
title bar, "Open" default, and `.iprj`-vs-image checks keep working; `pair`
is the extra state the save logic consults.

**Sensor renumbering is free.** `save_iprj` enumerates `project.sensors`, so a
fresh `Project(sensors=[sensor3, sensor4])` serializes them as
`Radarsensor_0/1` automatically. There is **no manual index renumbering** — do
not write index-rewriting code.

**Do NOT renumber `OutputNumber`.** Output numbers are project-wide
detector-rack channels (one physical controller input each — see
`next_output_number` and IPRJ_FORMAT). They must be preserved byte-for-byte
across the split; the `_3_4` file keeps outputs `33, 34, …` exactly as edited.
"Renumbered 1-2" in the ROADMAP means the **sensor index only**, nothing else.

---

## 3. Decision — canonical origin + background-match check

### 3a. Canonical origin (top-left = 0,0) — see also new [[ROADMAP.md]] Item 11

**Every project is normalized on load so the background image's top-left sits
at world (0,0).** iprj world space places the image top-left at
`(pos_x, pos_y)` and *all* objects — event/ignore zone points, sensor
positions, ETA points, reference points, lineals, text labels — live in that
same frame (IPRJ_FORMAT §"Coordinate system"). So translating everything by
`(−pos_x, −pos_y)` and setting `pos_x = pos_y = 0` re-expresses the whole
project relative to a **fixed insertion point**, instead of the arbitrary
"view at time of save" the vendor writes. Save writes `pos = (0,0)` too — we
deliberately depart from vendor byte-fidelity here (this is why it's its own
item; it changes the round-trip contract for *all* files, not just paired
ones).

This is exactly what the "positions can differ but everything must shift by
the same x/y delta" requirement needs: each file is independently shifted by
*its own* `(−pos_x, −pos_y)`, which preserves every object's position relative
to the image. Because a matched pair shares the **same image**, "relative to
top-left" is a common frame, so the two files coregister automatically — no
cross-file delta is ever computed, and the merge is a plain sensor-list
append (§5). Calibration is translation-invariant (`effective_meter_per_pixel`
uses the *distance* between reference points), so normalization never touches
the scale.

Item 9 assumes this normalization is in place (Item 11 lands first, or at
minimum the overlay path normalizes both projects before match/merge). Under
it, the match's position check is just a post-normalization sanity assert
(both ≈ 0,0), not a cross-file comparison.

### 3b. The match check

The `_3_4` file is written with a **deep copy of the same `Background`**, so a
pair produced by this tool matches by construction. The check exists for the
**overlay-open** path, where a user could pick two unrelated files. Both
projects are origin-normalized (§3a) before it runs.

Comparison is **two-tier**, checked in this order (first divergence wins):

**Tier 1 — geometry (hard fail).** Any mismatch here makes overlaying the
zones meaningless, so it blocks:
| Field | Rule |
|---|---|
| image dimensions | `background_image_size(a) == background_image_size(b)` — exact |
| `pos_x`, `pos_y` | both ≈ (0,0) post-normalization; `abs diff ≤ 0.01`. A residual difference means one file wasn't normalized — treat as a hard fail, not a real background mismatch. Raw pre-normalization `pos` differences between the source files are *expected and fine*. |
| `scale` | `abs diff ≤ 0.01` |
| `rotation` | `abs diff ≤ 0.01` |
| effective m/px | `abs(effective_meter_per_pixel(a) − …(b)) ≤ 0.005` (same tol `units` already uses) |

**Tier 2 — image content (soft warn).** If Tier 1 passes but
`sha256(decode_background_image(a)) != sha256(…(b))`, the two share size and
calibration but not pixels (e.g. one was re-encoded). Return `ok=True,
warn=True` — the GUI asks for confirmation rather than blocking, because the
geometry is what makes the overlay valid.

Return a small result rather than a bare bool so the GUI can show *why*:

```python
@dataclass
class BackgroundMatch:
    ok: bool          # False → hard fail, block
    warn: bool        # True with ok → soft mismatch, confirm
    reason: str       # e.g. "image is 1920×1080 vs 1600×900"
```

`reason` names the first field that diverged, with both values, ready to drop
into a `ui.notify`.

---

## 4. Decision — save-path restriction

Driven by one predicate: `is_multifile = len([s for s in sensors]) > 2`
(count real sensors).

**≤2 sensors → unchanged.** `Viewer.pair is None`; `save()`/`save_as()` behave
exactly as today, one `.iprj`.

**3–4 sensors → the pair rule:**
- **Plain Save is allowed only when `v.pair` is a valid naming pair** — same
  directory, stems differing only in `_1_2`/`_3_4` (validated by
  `is_valid_pair`, §5). Then Save writes **both** files from the split.
- **Otherwise Save is redirected to Save-As.** This covers the common case: a
  single-file project (opened from `foo.iprj`, `pair=None`) that the user
  grows to 3 sensors. There is no legal pair of paths to overwrite, so Save
  must not silently invent one — it opens Save-As.
- **Save-As takes one name and derives both.** The user enters a single path;
  `pair_paths()` (§5) strips any trailing `_1_2`/`_3_4` from the stem to get
  the base and returns `(base_1_2.iprj, base_3_4.iprj)`. Both are written; on
  success `v.pair` is set to them and `v.source` to the `_1_2` path, so the
  *next* plain Save works.

**Project-wide extras ownership (split rule).** Lineals, text labels,
centerlines-as-lineals, and `project.extra` are project-wide, not per-sensor.
To keep the split losslessly reversible, **the `_1_2` (primary) file owns them;
the `_3_4` file carries only the identical background + its two sensors.** On
merge, project-wide fields are taken from the primary and the secondary's are
ignored (they're just the duplicated background). Tradeoff to document in
IPRJ_FORMAT.md: opening the `_3_4` file *alone* in the vendor viewer shows its
zones but not the project-wide annotations/centerline guides — acceptable,
since zone geometry is baked into world coordinates and the annotations are
cosmetic.

---

## 5. Fable scope — `model/multifile.py` (pure python, pytest)

New module, no GUI imports, same testability bar as the rest of `model/`.

**Naming helpers** (pure string/Path):
```python
_PAIR_RE = re.compile(r"^(.*)_(1_2|3_4)$")   # on the stem

def pair_paths(one: Path) -> tuple[Path, Path]:
    """Any member path (or an unsuffixed base) -> (path_1_2, path_3_4).
    Strips a trailing _1_2/_3_4 from the stem to get the base."""

def is_valid_pair(p1: Path, p2: Path) -> bool:
    """True iff same parent dir and stems are <base>_1_2 / <base>_3_4."""

def pair_role(path: Path) -> str | None:   # "1_2" | "3_4" | None
```

**Background match** (§3):
```python
def check_background_match(a: Background, b: Background) -> BackgroundMatch
```
Uses `units.background_image_size`, `units.effective_meter_per_pixel`,
`units.decode_background_image`. Handles the no-image / no-calibration cases
by degrading gracefully (missing calibration on both → skip that tier; on one
only → hard fail with a clear reason).

**Split** (§2, §4):
```python
def split_project(project: Project) -> tuple[Project, Project | None]:
    """(-> primary, secondary). secondary is None when ≤2 sensors.
    Primary  = sensors[0:2] + all project-wide fields (background, lineals,
               text_labels, extra, date, version, product_code).
    Secondary= sensors[2:4] + a DEEP COPY of the background only.
    Deep-copies everything so the two Projects never alias the same Sensor/
    Background objects. OutputNumbers untouched. Raises if >4 sensors."""
```
Count "real" vs placeholder sensors consistently with how the GUI counts them
(mirror `add_sensor`/`delete_sensor`; a trailing blank default sensor should
not force a spurious second file).

**Merge** (§3, §4):
```python
def merge_pair(primary: Project, secondary: Project) -> Project:
    """primary (_1_2) + secondary (_3_4) -> one Project with sensors
    [p0, p1, s0, s1]. Project-wide fields come from primary; secondary
    contributes only its sensors. Calls check_background_match first and
    raises BackgroundMismatch(match.reason) on a hard fail (the soft-warn
    case is the GUI's call, so return the match alongside or expose a
    can_merge()/merge() split — see note)."""
```
Suggested shape: a pure `merge_pair(primary, secondary, *, allow_soft=False)`
that raises on hard fail and, unless `allow_soft`, also raises on the
soft-warn case — the GUI calls `check_background_match` first to decide whether
to pass `allow_soft=True` after the user confirms.

Guard: combined sensor count >4 → raise (shouldn't happen from tool-made
files; protects against a user overlaying two `_1_2` files).

**Tests** (`tests/test_multifile.py`, against `sites/**` fixtures read-only):
- `pair_paths`/`is_valid_pair`/`pair_role` incl. a base whose name itself ends
  in digits (`route_12` → `route_12_1_2.iprj`, not mis-stripped).
- Round-trip: build a 3- and a 4-sensor Project → `split_project` →
  `save_iprj` both → `load_iprj` both → `merge_pair` → assert deep-equal to
  the original (sensors, zones, conditions, **OutputNumbers**, points,
  background). This is the acceptance test.
- `_3_4` file's sensors serialize as `Radarsensor_0/1` and its OutputNumbers
  equal the originals (no renumber).
- `check_background_match`: identical pass; each Tier-1 field mismatch →
  `ok=False` with the right `reason`; same-geometry different-pixels →
  `ok=True, warn=True`; missing-calibration cases.
- ≤2 sensors → `split_project` returns `(proj, None)` and the primary equals a
  plain single-file save.

Hand Fable, as read-only context: this plan, `model/iprj_io.py`,
`model/units.py`, and the `Background`/`Sensor`/`Project` dataclasses. It does
**not** need the GUI.

---

## 6. Sonnet scope — File menu + save wiring in `gui/app.py`

Once `model/multifile.py` exists:

**`Viewer`:** add `self.pair: tuple[Path, Path] | None = None` (§2). Set it in
`open_project`/overlay-open and in the multi-file Save-As.

**Cap `add_sensor` at 4** (§1): if `len(real sensors) >= 4`, `ui.notify` "max
4 sensors (two-file limit)" and return before appending.

**New File-menu action — "Open second sensor-pair file (overlay)":** enabled
when a project is already open. Flow:
1. File picker / path input for the second `.iprj` (reuse `open_existing`'s
   known-sites select + path input).
2. Determine primary vs secondary from filenames via `pair_role`: if current
   `v.source` is `_1_2` and the picked file is `_3_4`, primary=current; if
   reversed, primary=picked. If neither follows the convention, **prompt which
   file is 1-2 vs 3-4** (two-button dialog).
3. `m = check_background_match(primary.bg, secondary.bg)`. Hard fail
   (`not m.ok`) → `ui.notify(m.reason, type="negative")`, stop. Soft
   (`m.warn`) → confirm dialog quoting `m.reason`; on cancel, stop.
4. `merged = merge_pair(primary_proj, secondary_proj, allow_soft=…)`;
   `swap_viewer(Viewer(merged, primary_path))` and set the new viewer's
   `pair = (path_1_2, path_3_4)`. (Set `pair` on the freshly built Viewer
   before/around `swap_viewer` — follow how `swap_viewer` hands state to the
   next page load.)

**`do_save`** grows a two-file branch:
```
if not is_multifile(v.project):         # ≤2 sensors — today's path
    save_iprj(v.project, path); ...
else:
    primary, secondary = split_project(v.project)
    p12, p34 = pair_paths(path)         # path is the _1_2 target
    save_iprj(primary, p12); save_iprj(secondary, p34)
    v.pair = (p12, p34); v.source = p12
    notify "saved <p12> + <p34>"
```
Keep the existing `save_centerlines`/`save_lineals` calls **before** the split
(they mutate the single in-memory Project; the split then routes the resulting
lineals to the primary per §4).

**`save()`:**
```
if not is_multifile(v.project):
    (existing: do_save on v.source if .iprj else save_as)
elif v.pair and is_valid_pair(*v.pair):
    do_save(v.pair[0])                  # writes both
else:
    save_as()                           # no legal pair yet — force naming
```

**`save_as()`** for a multi-file project: one path input as today; on apply,
`p12, p34 = pair_paths(entered)`, `do_save(p12)` (which now writes both).
Show the derived `_1_2`/`_3_4` names in the dialog so the user sees two files
will be written. The ≤2-sensor Save-As is unchanged.

**Optional polish:** in the toolbar/title, when `is_multifile`, show both file
names or a "2-file" badge so the user knows a Save touches two files.

---

## 7. Sequencing & docs

1. **Item 11 first (Fable):** origin-normalization (`normalize_origin`), so
   the whole app works in image-origin coordinates and the §3 match is a
   same-frame comparison. (No Item-3 prerequisite — the load path is sound;
   see intro.)
2. **Fable:** `model/multifile.py` + `tests/test_multifile.py`. Green suite is
   the gate.
3. **Sonnet:** the `gui/app.py` wiring above.
4. Update **IPRJ_FORMAT.md** with the `_1_2`/`_3_4` convention and the
   primary-owns-project-wide-extras rule; log the decisions in
   [[DESIGN_HISTORY.md]] and check Item 9's boxes in [[ROADMAP.md]].

## 8. Open questions / for later (non-blocking)

**Centerline locality.** Centerlines attached to a sensor-3/4 zone are saved
as project-wide lineals and therefore land in the `_1_2` file under the
primary-owns rule, so the `_3_4` file alone won't redraw that guide. Zone
world-coordinates are already baked, so this is display-only and fine for v1.
If per-file centerline locality is ever wanted, revisit whether the split
should route a lineal to the file whose sensor's zones reference it — out of
scope for Item 9.

**For later — per-sensor lineal index ranges (accepted limitation for now).**
The owner isn't happy that *all* lineals/markups have to live in the `_1_2`
file, but accepts it for v1. Possible future fix: **reserve an index range per
sensor** (e.g. lineals `Lineals_0..N` for file _1_2, a higher block for
_3_4) so each file carries only its own markups and the merge reassembles by
range. This hinges on a vendor-software experiment the owner will run:
- Does the vendor load a sparse/out-of-order lineal index — e.g. a
  `Lineals_15_*` with no `Lineals_0..14`?
- If so, does it **re-save at the same index**, or **renumber to the lowest
  free slot** on write?
If out-of-order indices survive a vendor round-trip, the reserved-range scheme
is viable; if the vendor compacts them, it isn't and primary-owns stays.
Record the experiment's outcome here before scoping this.
