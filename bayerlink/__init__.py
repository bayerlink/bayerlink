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
from . import pattern, tunnel

__version__ = "0.3.0"

__all__ = [
    "Header", "encode_frame", "encode_packed", "decode_frame", "pack_samples", "unpack_samples",
    "encode_stripes", "reassemble", "split_stripes",
    "check_geometry", "fits_line_rate", "fourcc_for",
    "BAYER_PHASE", "FLAG_TEST_PATTERN", "pattern",
    "detect_lane_map", "tunnel",
]
