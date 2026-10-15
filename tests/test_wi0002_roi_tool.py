"""WI-0002: ROI tool on the Viewer tab, the parts that need no display.

R2 "Viewport/UI: a ROI tool toggle (off / square / circle) on the Viewer tab; drag draws the shape as
   an overlay; release sets the ROI; Esc or tool off clears it. The voxel-click behaviour is unchanged
   when the tool is off."
   - tool state, drag, release and cancel: RoiDrag tests below (Tk-free, core/roi.py).
   - the drag lands on the right voxels of the shown image: test_drag_selects_the_dragged_image_pixels.
   - the overlay follows the controller (set, clear, drop on slice change): test_controller_publishes_*.
   The Tk widgets (radio buttons, canvas bindings, Esc, overlay drawing) are listed for a manual look
   in docs/dev/gui.md.
"""

from __future__ import annotations

import numpy as np
import pytest

from brkraw_viewer.core.roi import (
    RoiDrag,
    plane_axis,
    rc_to_uv,
    roi_extent,
    roi_mask,
    uv_to_rc,
)
from test_wi0005_roi_timecourse import env  # noqa: F401  (fixture: controller on a 4D phantom)


@pytest.mark.parametrize("plane,axis", [("xy", 2), ("xz", 1), ("zy", 0)])
def test_plane_axis(plane, axis):
    assert plane_axis(plane) == axis


def test_plane_axis_unknown():
    with pytest.raises(ValueError):
        plane_axis("yx")


@pytest.mark.parametrize("plane", ["xy", "xz", "zy"])
def test_rc_uv_round_trip(plane):
    assert uv_to_rc(plane, *rc_to_uv(plane, 3, 7)) == (3.0, 7.0)


def test_tool_off_does_nothing():
    d = RoiDrag()
    assert not d.active
    assert d.press("xy", 1, 1) is False
    assert d.release("xy", 4, 4) is None


def test_unknown_tool_raises():
    with pytest.raises(ValueError):
        RoiDrag().set_tool("triangle")


def test_square_drag_release_gives_set_roi_arguments():
    d = RoiDrag()
    d.set_tool("square")
    assert d.press("xy", 2, 1)  # image (row=y, col=x) -> u=x=1, v=y=2
    assert d.dragging
    out = d.release("xy", 5, 4)
    assert out == (2, "rect", (1, 4, 2, 5))
    assert not d.dragging


def test_circle_drag_gives_centre_and_radius():
    d = RoiDrag()
    d.set_tool("circle")
    d.press("zy", 2, 2)  # zy image is (y, z): u=row, v=col
    axis, shape, geom = d.release("zy", 6, 2)
    assert (axis, shape) == (0, "ellipse")
    assert geom == (4.0, 2.0, 2.0, 2.0)


def test_click_without_drag_sets_nothing():
    d = RoiDrag()
    d.set_tool("square")
    d.press("xy", 3, 3)
    assert d.release("xy", 3, 3) is None


def test_cancel_and_tool_change_drop_the_drag():
    d = RoiDrag()
    d.set_tool("square")
    d.press("xy", 1, 1)
    d.cancel()
    assert d.release("xy", 4, 4) is None
    d.press("xy", 1, 1)
    d.set_tool("off")
    assert not d.dragging and d.release("xy", 4, 4) is None


def test_release_on_another_plane_is_dropped():
    d = RoiDrag()
    d.set_tool("square")
    d.press("xy", 1, 1)
    assert d.move("xz", 3, 3) is None
    assert d.release("xz", 3, 3) is None


def test_move_returns_the_shape_to_draw():
    d = RoiDrag()
    d.set_tool("square")
    d.press("xy", 1, 1)
    assert d.move("xy", 1, 1) is None
    plane, shape, ext = d.move("xy", 3, 4)
    assert (plane, shape) == ("xy", "rect")
    assert ext == (1.0, 4.0, 1.0, 5.0)  # rows 1..3, cols 1..4 as pixel edges


@pytest.mark.parametrize("plane,axis", [("xy", 2), ("xz", 1), ("zy", 0)])
def test_drag_selects_the_dragged_image_pixels(plane, axis):
    # a 3D volume shown the way the controller builds its three images
    vol = np.arange(7 * 6 * 5, dtype=float).reshape(7, 6, 5)
    index = 2
    img = {"xy": vol[:, :, index].T, "xz": vol[:, index, :].T, "zy": vol[index, :, :]}[plane]
    d = RoiDrag()
    d.set_tool("square")
    d.press(plane, 1, 0)
    ax, shape, geom = d.release(plane, 3, 2)
    assert ax == axis and shape == "rect"
    slice2d = np.take(vol, index, axis=axis)
    mask = roi_mask(shape, slice2d.shape, geom)
    picked = np.sort(slice2d[mask])
    dragged = np.sort(img[1:4, 0:3].ravel())  # image rows 1..3, cols 0..2
    assert np.array_equal(picked, dragged)


@pytest.mark.parametrize("plane", ["xy", "xz", "zy"])
def test_extent_covers_the_mask_in_image_space(plane):
    geom = (1, 3, 2, 5)
    r0, r1, c0, c1 = roi_extent(plane, "rect", geom)
    u0, u1, v0, v1 = geom
    ra, ca = uv_to_rc(plane, u0, v0)
    rb, cb = uv_to_rc(plane, u1, v1)
    assert (r0, c0) == (min(ra, rb), min(ca, cb))
    assert (r1, c1) == (max(ra, rb) + 1, max(ca, cb) + 1)


def test_extent_ellipse_and_errors():
    assert roi_extent("zy", "ellipse", (4.0, 2.0, 2.0, 2.0)) == (2.5, 6.5, 0.5, 4.5)
    with pytest.raises(ValueError):
        roi_extent("xy", "star", (0, 0, 1, 1))
    with pytest.raises(ValueError):
        roi_extent("xy", "rect", (0, 1))


class _Recorder:
    def __init__(self):
        self.rois = []

    def __getattr__(self, name):
        return lambda *a, **k: None

    def set_viewer_roi(self, roi):
        self.rois.append(roi)

    def after(self, ms, func):
        func()


def test_controller_publishes_set_and_clear(env):  # noqa: F811
    view = _Recorder()
    env._view = view
    env.on_viewer_roi_set("rect", (1, 3, 1, 2), 2)
    assert view.rois[-1] == ("rect", (1.0, 3.0, 1.0, 2.0), 2)
    assert env.roi_timecourse()["n_mask"] == 6
    env.on_viewer_roi_clear()
    assert view.rois[-1] is None and env.roi_timecourse() is None


def test_controller_drops_the_overlay_on_slice_change(env):  # noqa: F811
    view = _Recorder()
    env._view = view
    env.on_viewer_roi_set("rect", (1, 3, 1, 2), 2)
    env.on_viewer_axis_change("z", env.state.viewer.z_index + 1)
    assert view.rois[-1] is None


def test_bad_drag_geometry_is_not_fatal(env):  # noqa: F811
    view = _Recorder()
    env._view = view
    env.on_viewer_roi_set("star", (1, 3, 1, 2), 2)
    assert env.roi_timecourse() is None
