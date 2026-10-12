# Copyright 2026 Serge Rabyking
# SPDX-License-Identifier: Apache-2.0
import pytest

from bayerlink.rasters import ALIASES, RASTERS, raster


@pytest.mark.parametrize("name", sorted(RASTERS))
def test_every_raster_is_a_raster(name):
    """Active area, then the sync inside the blanking after it."""
    r = RASTERS[name]
    assert r.h_active < r.hs_beg < r.hs_end <= r.h_total, name
    assert r.v_active < r.vs_beg < r.vs_end <= r.v_total, name


@pytest.mark.parametrize("name, hz", [("1080p30", 30), ("1080p60", 60),
                                      ("1080p24", 24), ("1080p25", 25),
                                      ("1080p50", 50), ("720p60", 60),
                                      ("480p120", 120), ("vga", 60)])
def test_a_raster_scans_at_the_rate_its_name_says(name, hz):
    assert raster(name).hz == hz


def test_every_short_name_names_a_raster():
    assert all(target in RASTERS for target in ALIASES.values())
    assert raster("1080p30") is RASTERS["1920x1080p30"]


def test_an_unknown_raster_is_refused_with_the_known_ones():
    with pytest.raises(KeyError, match="1920x1080p30"):
        raster("1080p23")
