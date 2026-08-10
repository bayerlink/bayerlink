"""Regenerate the conformance vectors. A diff here is a protocol change."""
import pathlib

from bayerlink import encode_frame, encode_stripes, pattern
from bayerlink.protocol import FLAG_TEST_PATTERN

HERE = pathlib.Path(__file__).parent

SPEC = [("corners_16x4_rggb", "corners", 16, 4, "RGGB", 3, 12),
        ("counting_16x8_bggr", "counting", 16, 8, "BGGR", 0, 12),
        ("counting_16x8_rggb10p", "counting", 16, 8, "RGGB", 0, 10),
        ("counting_16x8_grey8", "counting", 16, 8, None, 0, 8)]

for name, mode, width, height, order, seq, bits in SPEC:
    frame = encode_frame(pattern.generate(mode, width, height), order,
                         frame_seq=seq, display=(width, height + 4),
                         flags=FLAG_TEST_PATTERN, bits=bits)
    out = HERE / f"{name}.bin"
    out.write_bytes(frame.tobytes())
    print(f"wrote {out.name}: {out.stat().st_size} bytes")

# The same counting frame as two stripes -- one container per link. Each is
# an independently valid stream; together they pin the striping fields and
# the reassembly rules.
for index, container in enumerate(encode_stripes(
        pattern.generate("counting", 16, 8), "BGGR", frame_seq=0,
        stripes=2, display=(16, 8), flags=FLAG_TEST_PATTERN)):
    out = HERE / f"counting_16x8_bggr_stripe{index}of2.bin"
    out.write_bytes(container.tobytes())
    print(f"wrote {out.name}: {out.stat().st_size} bytes")
