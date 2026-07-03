"""Zoom/pan state for the image viewer — pure math, no GUI imports.

The image element keeps its natural pixel size and is moved/zoomed with a CSS
transform `translate(tx, ty) scale(scale)` (origin top-left), so a point p in
image coordinates appears at viewport position  v = t + scale * p.  Mouse
events keep reporting untransformed image coordinates, which makes the
handlers trivial: all viewport math lives here.
"""

from __future__ import annotations

from dataclasses import dataclass

Point = tuple[float, float]

MIN_SCALE = 0.01
MAX_SCALE = 40.0


@dataclass
class Viewport:
    scale: float = 1.0
    tx: float = 0.0
    ty: float = 0.0

    def css(self) -> str:
        return (f"transform-origin: 0 0; "
                f"transform: translate({self.tx}px, {self.ty}px) scale({self.scale});")

    def zoom_at(self, image_point: Point, factor: float) -> None:
        """Zoom by `factor`, keeping `image_point` fixed on screen."""
        new_scale = min(MAX_SCALE, max(MIN_SCALE, self.scale * factor))
        factor = new_scale / self.scale
        # v = t + s*p stays put:  t' = t + s*p*(1 - k)
        self.tx += self.scale * image_point[0] * (1.0 - factor)
        self.ty += self.scale * image_point[1] * (1.0 - factor)
        self.scale = new_scale

    def drag_to(self, anchor: Point, image_point: Point) -> None:
        """Pan so the cursor (now over `image_point`) drags `anchor` with it.

        Both points are in image coordinates as reported *during the same
        transform state*; applying per mousemove keeps the anchor glued to
        the cursor.
        """
        self.tx += self.scale * (image_point[0] - anchor[0])
        self.ty += self.scale * (image_point[1] - anchor[1])

    def fit(self, image_size: Point, viewport_size: Point, margin: float = 0.98) -> None:
        """Scale and center the whole image inside the viewport."""
        iw, ih = image_size
        vw, vh = viewport_size
        if iw <= 0 or ih <= 0 or vw <= 0 or vh <= 0:
            return
        self.scale = min(MAX_SCALE, max(MIN_SCALE, margin * min(vw / iw, vh / ih)))
        self.tx = (vw - self.scale * iw) / 2.0
        self.ty = (vh - self.scale * ih) / 2.0

    def image_to_viewport(self, p: Point) -> Point:
        return (self.tx + self.scale * p[0], self.ty + self.scale * p[1])
