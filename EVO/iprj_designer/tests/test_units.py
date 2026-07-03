import math
from pathlib import Path

import pytest

from model.iprj_io import Background, load_iprj
from model import units

SITES = Path(__file__).resolve().parents[3] / "sites"


def test_basic_conversions():
    assert units.ft_to_m(1.0) == 0.3048
    assert units.m_to_ft(0.3048) == pytest.approx(1.0)
    # 0.25 ft/px <-> 0.0762 m/px (the Banks calibration)
    assert units.px_to_ft(1.0, 0.0762) == pytest.approx(0.25)
    assert units.ft_to_px(0.25, 0.0762) == pytest.approx(1.0)
    assert units.px_to_m(10.0, 0.2) == pytest.approx(2.0)
    assert units.m_to_px(2.0, 0.2) == pytest.approx(10.0)


def test_calibrate_two_points():
    bg = Background()
    units.calibrate_two_points(bg, (0.0, 0.0), (0.0, 4800.0), 1200.0)
    assert bg.reference_length == pytest.approx(365.76)  # 1200 ft in meters
    assert bg.meter_per_pixel == pytest.approx(0.0762)
    assert (bg.ref1_x, bg.ref1_y) == (0.0, 4800.0)
    assert units.ft_per_px(bg) == pytest.approx(0.25)


def test_calibrate_two_points_rejects_degenerate():
    bg = Background()
    with pytest.raises(ValueError):
        units.calibrate_two_points(bg, (5.0, 5.0), (5.0, 5.0), 100.0)
    with pytest.raises(ValueError):
        units.calibrate_two_points(bg, (0.0, 0.0), (1.0, 0.0), 0.0)


def test_calibrate_image_width():
    bg = Background(pos_x=-100.0, pos_y=50.0)
    units.calibrate_image_width(bg, image_width_px=1600.0, width_ft=400.0)
    assert units.ft_per_px(bg) == pytest.approx(0.25)
    assert (bg.ref0_x, bg.ref0_y) == (-100.0, 50.0)
    assert (bg.ref1_x, bg.ref1_y) == (1500.0, 50.0)


def test_effective_mpp_prefers_reference_pair():
    # Vendor stores MeterPerPixel rounded to 2 decimals; the reference pair
    # carries full precision (banks.iprj: stored 0.08, implied 0.0762).
    bg = Background(meter_per_pixel=0.08, reference_length=365.76,
                    ref0_x=0.0, ref0_y=0.0, ref1_x=0.0, ref1_y=4800.0)
    assert units.effective_meter_per_pixel(bg) == pytest.approx(0.0762)


def test_effective_mpp_ignores_stale_reference_pair():
    # ex27bg2.iprj: ReferenceLength edited without re-applying calibration,
    # so the implied value (0.066) disagrees with stored (0.22) beyond
    # rounding -> trust stored.
    bg = Background(meter_per_pixel=0.22, reference_length=3.05,
                    ref0_x=0.0, ref0_y=0.0, ref1_x=46.31, ref1_y=0.0)
    assert units.effective_meter_per_pixel(bg) == 0.22


def test_effective_mpp_no_calibration_raises():
    with pytest.raises(ValueError):
        units.effective_meter_per_pixel(Background())


def test_effective_mpp_against_real_banks_file():
    project = load_iprj(SITES / "Banks" / "banks.iprj")
    mpp = units.effective_meter_per_pixel(project.background)
    assert mpp == pytest.approx(0.0762, abs=1e-4)
    assert units.ft_per_px(project.background) == pytest.approx(0.25, abs=1e-3)


def test_background_image_size_real_file():
    project = load_iprj(SITES / "Banks" / "banks.iprj")
    assert units.background_image_size(project.background) == (2000, 4800)
