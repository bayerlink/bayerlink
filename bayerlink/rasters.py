# Copyright 2026 Serge Rabyking
# SPDX-License-Identifier: Apache-2.0
"""The display rasters a link runs on, from CEA-861.

A raster is the whole scanned frame: its totals, its active area, where
its syncs sit and which way they point, and the pixel clock that scans
it. Both ends of a link need the same numbers -- the source to set its
output, the receiver to advertise the mode in its EDID, a display
behind the receiver to scan out -- so they live here, once, and every
end reads them rather than keeping a copy.

Positions count from the first active pixel (line), so a sync window
``hs_beg..hs_end`` is ``[hs_beg, hs_end)`` on the same counter that
counts the active area from zero.
"""
from __future__ import annotations

from typing import NamedTuple


class Raster(NamedTuple):
    h_total: int
    v_total: int
    h_active: int
    v_active: int
    hs_beg: int
    hs_end: int
    vs_beg: int
    vs_end: int
    pixel_khz: int
    hsync_positive: bool
    vsync_positive: bool

    @property
    def hz(self) -> int:
        """The frame rate, to the nearest whole frame: 119.88 is 120."""
        return round(self.pixel_khz * 1000 / (self.h_total * self.v_total))


RASTERS = {
    #                     h_tot v_tot h_act v_act hs_beg hs_end vs_beg vs_end  kHz   +h     +v
    "640x480p60":   Raster(800,  525,  640,  480,  656,  752,  490,  492,  25175, False, False),
    "720x480p60":   Raster(858,  525,  720,  480,  736,  798,  489,  495,  27000, False, False),
    # VIC 48, the slowest standard raster that scans faster than 60
    # frames a second: for a sensor that reads out faster than that.
    "720x480p120":  Raster(858,  525,  720,  480,  736,  798,  489,  495,  54000, False, False),
    "1280x720p60":  Raster(1650, 750, 1280,  720, 1390, 1430,  725,  730,  74250, True, True),
    "1280x720p50":  Raster(1980, 750, 1280,  720, 1720, 1760,  725,  730,  74250, True, True),
    "1920x1080p24": Raster(2750, 1125, 1920, 1080, 2558, 2602, 1084, 1089,  74250, True, True),
    "1920x1080p25": Raster(2640, 1125, 1920, 1080, 2448, 2492, 1084, 1089,  74250, True, True),
    "1920x1080p30": Raster(2200, 1125, 1920, 1080, 2008, 2052, 1084, 1089,  74250, True, True),
    "1920x1080p50": Raster(2640, 1125, 1920, 1080, 2448, 2492, 1084, 1089, 148500, True, True),
    "1920x1080p60": Raster(2200, 1125, 1920, 1080, 2008, 2052, 1084, 1089, 148500, True, True),
}

ALIASES = {"vga": "640x480p60", "480p60": "720x480p60",
           "480p120": "720x480p120", "720p60": "1280x720p60",
           "720p50": "1280x720p50", "1080p24": "1920x1080p24",
           "1080p25": "1920x1080p25", "1080p30": "1920x1080p30",
           "1080p50": "1920x1080p50", "1080p60": "1920x1080p60"}


def raster(name: str) -> Raster:
    """A raster by its name (``1920x1080p30``) or short name (``1080p30``)."""
    key = ALIASES.get(name, name)
    if key not in RASTERS:
        raise KeyError(f"no raster {name!r}; known: "
                       f"{', '.join(sorted(RASTERS))}, or "
                       f"{', '.join(sorted(ALIASES))}")
    return RASTERS[key]
