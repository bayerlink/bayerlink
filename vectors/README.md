# Conformance vectors

Each `.bin` is a complete bayerlink container -- the raw bytes of the
(display_height, display_width, 3) frame, row-major -- produced by the
reference implementation from a deterministic test pattern. An
implementation conforms when it produces these bytes exactly (encoder)
or recovers the pattern and header from them exactly (decoder).

| file | pattern | camera | container | bayer | frame_seq | flags |
| --- | --- | --- | --- | --- | --- | --- |
| `corners_16x4_rggb.bin` | corners | 16x4 | 16x8 | RGGB | 3 | test_pattern |
| `counting_16x8_bggr.bin` | counting | 16x8 | 16x12 | BGGR | 0 | test_pattern |

Regenerate with `python vectors/make.py`; a diff against the committed
files is a protocol change and needs a version discussion, not a quiet
update.
