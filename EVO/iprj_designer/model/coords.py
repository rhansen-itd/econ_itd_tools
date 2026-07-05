"""Canonical world-coordinate origin: background top-left = (0,0).

The vendor writes every coordinate relative to the view at the time of save,
so the background image's top-left lands at an arbitrary (Background_PosX,
Background_PosY) that drifts file to file. normalize_origin() re-expresses a
whole Project relative to a fixed insertion point instead — the image's
top-left at world (0,0) — by translating every coordinate field by
(-pos_x, -pos_y). load_iprj applies it to every loaded project, so the app
always reasons from one known datum and save naturally writes pos = (0,0).
See ROADMAP Item 11 and ITEM9_SPLIT_PLAN.md §3a (it's what lets a matched
two-file pair coregister without any cross-file delta).

Calibration (MeterPerPixel / ReferenceLength) is translation-invariant —
effective_meter_per_pixel uses only the *distance* between the reference
points — so it is deliberately untouched; the reference points themselves
shift with everything else.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .iprj_io import Point, Project


def normalize_origin(project: Project) -> Project:
    """Translate every coordinate so the background top-left is world (0,0).

    Shifts by (-pos_x, -pos_y): the background position and meter-reference
    points, sensor positions, event-zone vertices and ETA points, ignore-zone
    vertices, lineal endpoints, and text-label positions. Disabled vendor
    placeholder entries shift too — the whole file moves as one rigid frame.
    Fields that are None (converter-form files omit keys) stay None so save
    doesn't invent attributes. Idempotent; mutates in place and returns the
    same Project.
    """
    bg = project.background
    dx = bg.pos_x or 0.0
    dy = bg.pos_y or 0.0
    if dx == 0.0 and dy == 0.0:
        return project

    def sx(v: float | None) -> float | None:
        return None if v is None else v - dx

    def sy(v: float | None) -> float | None:
        return None if v is None else v - dy

    def spt(p: Point | None) -> Point | None:
        return None if p is None else (p[0] - dx, p[1] - dy)

    bg.pos_x = sx(bg.pos_x)
    bg.pos_y = sy(bg.pos_y)
    bg.ref0_x = sx(bg.ref0_x)
    bg.ref0_y = sy(bg.ref0_y)
    bg.ref1_x = sx(bg.ref1_x)
    bg.ref1_y = sy(bg.ref1_y)

    for sensor in project.sensors:
        sensor.position_x = sx(sensor.position_x)
        sensor.position_y = sy(sensor.position_y)
        for zone in sensor.event_zones:
            zone.eta_point_x = sx(zone.eta_point_x)
            zone.eta_point_y = sy(zone.eta_point_y)
            zone.points = [spt(p) for p in zone.points]
        for zone in sensor.ignore_zones:
            zone.points = [spt(p) for p in zone.points]

    for lineal in project.lineals:
        lineal.point_0 = spt(lineal.point_0)
        lineal.point_1 = spt(lineal.point_1)

    for label in project.text_labels:
        label.position_x = sx(label.position_x)
        label.position_y = sy(label.position_y)

    return project
