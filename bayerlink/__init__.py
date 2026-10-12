# Copyright 2026 Serge Rabyking
# SPDX-License-Identifier: Apache-2.0
"""bayerlink -- raw sensor data over an HDMI/DVI link.

The specification is PROTOCOL.md in this repository; this package is its
reference implementation, running on BOTH ends of a link: encoders build
containers with it, and receivers' host software decodes captured frames with
the same module. The committed vectors pin the exact bytes, so a conforming
implementation in any language never has to run this one.
"""
from .protocol import (
    BAYER_PHASE,
    detect_lane_map,
    FLAG_TEST_PATTERN,
    Header,
    check_geometry,
    decode_frame,
    encode_frame,
    encode_packed,
    encode_stripes,
    fits_line_rate,
    fourcc_for,
    pack_samples,
    reassemble,
    split_stripes,
    unpack_samples,
)
from . import pattern, rasters, recording

# The version has ONE owner: the packaging metadata in
# pyproject.toml. Read back from the INSTALLED distribution
# rather than restated here, so this can never claim a version
# other than the one pip actually resolved.
from importlib.metadata import version as _version

__version__ = _version("bayerlink")

__all__ = [
    "recording", "rasters",
    "Header", "encode_frame", "encode_packed", "decode_frame", "pack_samples", "unpack_samples",
    "encode_stripes", "reassemble", "split_stripes",
    "check_geometry", "fits_line_rate", "fourcc_for",
    "BAYER_PHASE", "FLAG_TEST_PATTERN", "pattern",
    "detect_lane_map",
]
