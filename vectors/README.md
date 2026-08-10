# Conformance vectors

Each `.bin` is a complete bayerlink container -- the raw bytes of the
(display_height, display_width, 3) frame, row-major -- produced by the
reference implementation from a deterministic test pattern. An
implementation conforms when it produces these bytes exactly (encoder)
or recovers the pattern and header from them exactly (decoder).

| file | pattern | camera | container | payload | frame_seq | flags |
| --- | --- | --- | --- | --- | --- | --- |
| `corners_16x4_rggb.bin` | corners | 16x4 | 16x8 | RGGB 12P | 3 | test_pattern |
| `counting_16x8_bggr.bin` | counting | 16x8 | 16x12 | BGGR 12P | 0 | test_pattern |
| `counting_16x8_rggb10p.bin` | counting | 16x8 | 16x12 | RGGB 10P | 0 | test_pattern |
| `counting_16x8_grey8.bin` | counting | 16x8 | 16x12 | mono 8-bit (`GREY`) | 0 | test_pattern |
| `counting_16x8_bggr_stripe0of2.bin` | counting, lines 0..3 | 16x4 band | 16x8 | BGGR 12P | 0 | test_pattern |
| `counting_16x8_bggr_stripe1of2.bin` | counting, lines 4..7 | 16x4 band | 16x8 | BGGR 12P | 0 | test_pattern |

The stripe pair is the SAME frame as `counting_16x8_bggr.bin`, split for
two links: decoding both and reassembling must reproduce that frame's
payload exactly.

Regenerate with `python vectors/make.py`; a diff against the committed
files is a protocol change and needs a version discussion, not a quiet
update.
