"""Regenerate the conformance vectors. A diff here is a protocol change."""
import pathlib

from bayerlink import encode_frame, pattern
from bayerlink.protocol import FLAG_TEST_PATTERN

SPEC = [("corners_16x4_rggb", "corners", 16, 4, "RGGB", 3),
        ("counting_16x8_bggr", "counting", 16, 8, "BGGR", 0)]

for name, mode, width, height, order, seq in SPEC:
    frame = encode_frame(pattern.generate(mode, width, height), order,
                         frame_seq=seq, display=(width, height + 4),
                         flags=FLAG_TEST_PATTERN)
    out = pathlib.Path(__file__).parent / f"{name}.bin"
    out.write_bytes(frame.tobytes())
    print(f"wrote {out.name}: {out.stat().st_size} bytes")
