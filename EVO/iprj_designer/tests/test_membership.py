"""Explicit, persisted centerline membership (ROADMAP Item 26).

Membership (which zones belong to which approach centerline) used to be
re-derived from geometry on load (`derive_attachments`). Item 26 makes it an
explicit set persisted as a per-centerline ``"name: sensor_zone slots"`` text
label, so it survives a round-trip without any geometric guessing. Members are
keyed by their (sensor, zone-index) vendor slot — unique and index-stable
across save/reload — written in absolute (merged-project) sensor space so a
bare _3_4 half resolves too. These tests drive the GUI `Viewer` headlessly.
"""

import base64
import io
from pathlib import Path

from PIL import Image

from gui.app import Viewer
from gui.drawing import element_owner
from model.bands import Owner
from model.centerline import save_centerlines_owned, save_lineals_owned
from model.iprj_io import (Background, EventZone, Project, Sensor, load_iprj,
                           save_iprj)
from model.labels import parse_membership_label, save_labels_owned
from model.multifile import split_project


def _bg() -> Background:
    buf = io.BytesIO()
    Image.new("RGB", (600, 600), "gray").save(buf, format="PNG")
    return Background(image_base64=base64.b64encode(buf.getvalue()).decode("ascii"),
                      pos_x=0.0, pos_y=0.0, scale=100.0)


def _triangle(name: str = "det") -> EventZone:
    # deliberately NOT a station/offset rectangle, so only explicit membership
    # (never the geometric fallback) can re-attach it on load
    return EventZone(enable=1, zone_name=name,
                     points=[(210.0, 300.0), (250.0, 300.0), (230.0, 340.0)])


def make_viewer(zones=None, tmp_path=None, name="membership_test") -> Viewer:
    sensor = Sensor()
    sensor.event_zones = list(zones or [])
    project = Project(background=_bg(), sensors=[sensor])
    src = (tmp_path or Path("/tmp")) / f"{name}.iprj"
    return Viewer(project, src)


def _persist(v: Viewer, path: Path) -> None:
    """The model-layer subset of do_save (no GUI): sync the managed labels,
    then write centerlines/lineals/labels into their bands and save."""
    v.sync_centerline_labels()
    v.sync_membership_labels()
    save_centerlines_owned(v.project, [(cl.owner, cl.points) for cl in v.centerlines])
    save_lineals_owned(v.project, [(element_owner(l), l) for l in v.lineals])
    save_labels_owned(v.project, [(element_owner(l), l) for l in v.labels])
    save_iprj(v.project, path)


def _name_centerline(v: Viewer, name="N_CL", owner=Owner.GENERAL):
    cl = v.centerlines[0]
    cl.points = [(200.0, 200.0), (200.0, 500.0)]
    cl.name = name
    cl.owner = owner
    return cl


def test_membership_persists_and_reloads_without_geometry(tmp_path):
    zone = _triangle()
    v = make_viewer([zone], tmp_path)
    cl = _name_centerline(v)
    assert v.set_zone_membership(zone, 0) is True
    assert v.member_slots(cl) == [(0, 0)]  # sensor 0, zone slot 0

    path = tmp_path / "m.iprj"
    _persist(v, path)
    assert any(parse_membership_label(l.text or "") == ("N_CL", [(0, 0)])
               for l in v.labels)

    v2 = Viewer(load_iprj(path), path)
    # membership drove reconstruction — no geometric fallback ran
    assert v2.derived_attachments == 0
    cl2 = next(c for c in v2.centerlines if c.name == "N_CL")
    assert id(v2.project.sensors[0].event_zones[0]) in cl2.attached


def test_membership_label_follows_centerline_owner_band(tmp_path):
    zone = _triangle()
    v = make_viewer([zone], tmp_path)
    _name_centerline(v, owner=Owner.FILE1)  # sensors 1&2 -> _1_2
    v.set_zone_membership(zone, 0)
    v.sync_centerline_labels()
    v.sync_membership_labels()
    memb = next(l for l in v.labels
                if parse_membership_label(l.text or "") is not None)
    # routing: the membership label is written to the centerline's band, so it
    # travels to _1_2 on the two-file split exactly like the name label
    assert element_owner(memb) == Owner.FILE1


def test_membership_label_dropped_when_unnamed_or_empty(tmp_path):
    zone = _triangle()
    v = make_viewer([zone], tmp_path)
    cl = v.centerlines[0]
    cl.points = [(200.0, 200.0), (200.0, 500.0)]  # unnamed
    v.set_zone_membership(zone, 0)
    v.sync_membership_labels()
    assert cl.membership_label is None            # unnamed -> not persisted
    assert not any(parse_membership_label(l.text or "") for l in v.labels)

    cl.name = "N_CL"
    v.sync_membership_labels()
    assert cl.membership_label is not None         # named + members -> label
    cl.detach(zone)
    v.sync_membership_labels()
    assert cl.membership_label is None             # no members -> dropped
    assert not any(parse_membership_label(l.text or "") for l in v.labels)


def test_standalone_3_4_half_reconstructs_membership(tmp_path):
    # 3-sensor project -> two-file split; a FILE2 centerline owns a zone in
    # sensor 2, which the _3_4 half stores renumbered as local sensor 0. The
    # absolute "2_0" slot must still resolve there via the pair-role offset.
    zone = _triangle()
    s0, s1, s2 = Sensor(), Sensor(), Sensor()
    s2.event_zones = [zone]
    project = Project(background=_bg(), sensors=[s0, s1, s2])
    src = tmp_path / "proj.iprj"           # role None -> absolute == local here
    v = Viewer(project, src)
    cl = _name_centerline(v, owner=Owner.FILE2)
    assert v.set_zone_membership(zone, 0) is True
    v.sync_centerline_labels()
    v.sync_membership_labels()
    memb = next(l for l in v.labels if parse_membership_label(l.text or ""))
    assert parse_membership_label(memb.text) == ("N_CL", [(2, 0)])  # absolute

    # persist into the project's bands, split, and write the _3_4 half alone
    save_centerlines_owned(v.project, [(c.owner, c.points) for c in v.centerlines])
    save_lineals_owned(v.project, [(element_owner(l), l) for l in v.lineals])
    save_labels_owned(v.project, [(element_owner(l), l) for l in v.labels])
    _, secondary = split_project(v.project)
    path34 = tmp_path / "proj_3_4.iprj"
    save_iprj(secondary, path34)

    v2 = Viewer(load_iprj(path34), path34)     # standalone _3_4 half
    assert v2._sensor_index_offset == 2
    assert len(v2.project.sensors) == 1        # renumbered to a lone sensor 0
    cl2 = next(c for c in v2.centerlines if c.name == "N_CL")
    assert id(v2.project.sensors[0].event_zones[0]) in cl2.attached


def test_pre_item26_file_still_derives_membership_geometrically(tmp_path):
    # an engine-placed (station/offset rectangle) zone with no membership label
    # falls back to derive_attachments so old projects keep working
    rect = EventZone(enable=1, output_number=1, points=[
        (220.0, 300.0), (232.0, 300.0), (232.0, 340.0), (220.0, 340.0)])
    v = make_viewer([rect], tmp_path)
    cl = v.centerlines[0]
    cl.points = [(200.0, 200.0), (200.0, 500.0)]
    # rebuild a viewer from a saved project that carries no membership labels
    save_centerlines_owned(v.project, [(cl.owner, cl.points)])
    path = tmp_path / "legacy.iprj"
    save_iprj(v.project, path)
    v2 = Viewer(load_iprj(path), path)
    assert v2.derived_attachments == 1  # geometric fallback ran
