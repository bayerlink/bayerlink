# bayerlink — raw sensor data over an HDMI/DVI link

**Version 2.** This document is the specification; `bayerlink/protocol.py` in
this repository is its reference implementation, and `vectors/` pins the exact
bytes, so the three ship together and a disagreement among them is a bug here,
not an interpretation question downstream.

**Independent implementation of this protocol is unrestricted and
encouraged.** The Apache-2.0 licence governs this repository's text and code,
not the ideas it describes; an implementation in any language, under any
licence, for any purpose, needs nobody's permission. Implementations may state
conformance -- "speaks bayerlink v2" -- but may not present the name as their
own; see TRADEMARK.md.

## The idea

A display link is a cheap, ubiquitous, line-locked transport: fixed timing,
24 bits per pixel, receivers available on nearly every FPGA board. bayerlink
treats the active video area as a **byte container** and carries raw sensor
data through it unmodified — packed Bayer samples in, packed Bayer samples
out — with one header line that makes the stream self-describing.

Nothing in this protocol is specific to any camera, any single-board computer,
or any FPGA. Any tool that emits these bytes is a bayerlink source, and any
receiver that parses the header may consume it; the known ones are listed at
the end of this document.

## Requirements on the link

The link must deliver the framebuffer bytes UNMODIFIED. Concretely:

- RGB output, **full range** (a limited-range clamp of 16..235 silently
  destroys sample data — this is the most common integration failure);
- no scaling, no overscan, no chroma subsampling (RGB 4:4:4 only);
- the display mode's active width and height are the container dimensions.

Byte-lane order (which memory byte arrives on which of the three 8-bit video
lanes) varies by scanout format and receiver; it is a fixed permutation of
three lanes, resolved once per platform pair with a test pattern. The
protocol is defined over the **memory byte sequence of each scanline**, not
over lane names.

## Layout

```
line 0            header (32 bytes, then zeros to end of line)
line 1..height    one camera line per display line: the camera line's packed
                  bytes, left-aligned, zero-padded to the display line width
remaining lines   zeros
```

One camera frame occupies one display frame. If the display refreshes faster
than the camera delivers, the SAME encoded frame is scanned out again,
`frame_seq` unchanged — a receiver deduplicates by `frame_seq`, never by
timing.

## Header

48 bytes at the start of line 0, all integers **little-endian**:

| Offset | Size | Field | Meaning |
| --- | --- | --- | --- |
| 0 | u32 | `magic` | `0x4B4C5942` — the bytes "BYLK" |
| 4 | u16 | `version` | protocol version; this document is 2 |
| 6 | u16 | `header_bytes` | 48; lets later versions grow the header |
| 8 | u32 | `fourcc` | payload format, a V4L2 raw fourcc (see below) |
| 12 | u32 | `width` | samples per camera line |
| 16 | u32 | `height` | camera lines THIS stream carries (a stripe's band, or the whole frame) |
| 20 | u32 | `frame_seq` | increments once per NEW camera frame |
| 24 | u32 | `flags` | bit 0: payload is a test pattern; other bits MBZ |
| 28 | u8 | `source_id` | which camera this stream carries |
| 29 | u8 | `stripe_index` | 0-based, `< stripe_count` |
| 30 | u8 | `stripe_count` | stripes this frame travels as; 1 = unstriped |
| 31 | u8 | reserved | MBZ |
| 32 | u32 | `stripe_offset` | first camera line of this stripe in the full frame |
| 36 | u32 | `full_height` | camera lines of the WHOLE frame |
| 40 | u32 | reserved | MBZ |
| 44 | u32 | `crc32` | CRC-32 (zlib) of bytes 0..43 |

A receiver MUST verify `magic`, `version` and `crc32`, MUST refuse a
`fourcc` it does not implement rather than guessing, and MUST refuse a
header whose MBZ (must-be-zero) bytes or flag bits are set: those belong to
a future dialect this document cannot promise to have kept compatible.
Evolution happens through `version`, never through quiet reinterpretation
of reserved space. Check `version` before `crc32` — earlier layouts kept
the CRC elsewhere, and "old version" is the right diagnosis where "corrupt"
would be wrong.

When `stripe_count` is 1, `stripe_index` and `stripe_offset` MUST be 0 and
`full_height` MUST equal `height`.

## Multiple links: striping and source identity

A frame larger than one link's budget travels as **contiguous line bands**
over several links — a Raspberry Pi 4 drives two HDMI outputs; two capture
sticks double a bench. Each stripe is an INDEPENDENTLY VALID bayerlink
stream: it decodes alone into its band, and it passes every rule in this
document per link (geometry, rate). The header carries the identity — which
slice, of which frame, from which camera — so pairing never depends on
capture timing: the scanout engines share no vsync.

- `stripe_offset` and every band's `height` MUST be even: a stripe boundary
  on an odd line flips the CFA phase mid-frame, which presents as a
  demosaic defect far from its cause.
- Bands MUST tile `[0, full_height)` exactly: no gap, no overlap.
- Stripes of one frame MUST agree on `fourcc`, `width`, `full_height`,
  `frame_seq`, `flags` and `source_id`.
- A receiver pairs stripes by (`source_id`, `frame_seq`), tolerating at
  least one frame of skew between links, and MUST drop ALL stripes of a
  frame whose set is incomplete: a torn frame is worse than a dropped one.

`source_id` distinguishes CAMERAS, not links: a stereo pair is two sources
(one stream each, or stripes each), and streams with different `source_id`
are never stripes of one another. Identity travels in-band.

## Payload formats

`fourcc` is the V4L2 pixel format code of the payload bytes, so the
packing, bit depth and plane meaning (a CFA order, or monochrome) travel in
ONE field that already has an authority defining it. A version-2 receiver
MUST implement at least the 12-bit packed Bayer family; every other row is
optional and refused by fourcc when not implemented.

All packed families follow the one CSI-2 rule: a GROUP of samples ships its
high eight bits as plain bytes, then the leftover low bits packed into
residue bytes, lowest sample first. 8-bit payloads are plain bytes; 16-bit
are little-endian pairs.

| Bits | Group | Layout |
| --- | --- | --- |
| 8 | 1 sample → 1 byte | `[ S0[7:0] ]` |
| 10 | 4 samples → 5 bytes | `[S0>>2][S1>>2][S2>>2][S3>>2][ S3[1:0] S2[1:0] S1[1:0] S0[1:0] ]` |
| 12 | 2 samples → 3 bytes | `[S0>>4][S1>>4][ S1[3:0] S0[3:0] ]` |
| 14 | 4 samples → 7 bytes | `[S0>>6][S1>>6][S2>>6][S3>>6]` + three bytes of the four 6-bit residues, lowest first |
| 16 | 1 sample → 2 bytes | `[ S0[7:0] ][ S0[15:8] ]` |

`width` must be a multiple of the packing group, and a payload line is
`width / group_samples * group_bytes` bytes. The rate rule below holds for
every family: the line FIFO absorbs each family's burst ratio within the
line, so the budget is stated in samples either way.

Note the header line's cost: a container of N display lines carries at most
N-1 camera lines, so a full-height 1080-line camera mode does NOT fit a
1080p display. The header also sets the minimum container width: 16 display
pixels (48 bytes) — met by every real display mode, stated for completeness
and for test rigs using tiny containers. The reference setup captures 2028x1078 — libcamera crops raw
streams freely, and an even height keeps whole 2x2 CFA rows.

The rate and geometry rules apply PER LINK: each stripe's container
carries that stripe's band, and each link is budgeted alone.

## Rate rule for one-sample-per-clock receivers

A display pixel carries two 12-bit samples, so a receiver processing one
sample per pixel-clock cycle keeps up iff

```
width  <=  total line slots of the display mode   (active + blanking)
```

because the padding and blanking absorb the 2-per-clock bursts through a
small line FIFO. Example: 2028-sample lines inside 1080p (2200 total slots)
fit; inside 720p (1650 slots) they do not. A receiver SHOULD carry a sticky
overflow flag so a violated budget is an observable error, not a corrupted
image.

## Versioning

`version` bumps when the header layout or its semantics change.
`header_bytes` lets a receiver skip unknown trailing header fields within a
version. New payload formats are NOT a version bump — they are new fourccs,
and the refusal rule handles them.

**Version 1** (32-byte header: no source or stripe identity, CRC at byte
28) is historical: it shipped only in this repository's releases up to
0.2.0, with no deployed sources. Current receivers refuse it by `version`.

## fourcc registry

Assigned — a conforming receiver implements at least the 12P Bayer family;
the rest is opt-in:

| fourcc | Payload | Status |
| --- | --- | --- |
| `pRCC` `pgCC` `pGCC` `pBCC` | 12-bit packed Bayer (V4L2 `*12P`) | assigned, mandatory |
| `pRAA` `pgAA` `pGAA` `pBAA` | 10-bit packed Bayer (V4L2 `*10P`) | assigned |
| `RGGB` `GRBG` `GBRG` `BA81` | 8-bit raw Bayer (V4L2 `*8`) | assigned |
| `pREE` `pgEE` `pGEE` `pBEE` | 14-bit packed Bayer (V4L2 `*14P`) | assigned |
| `RG16` `GR16` `GB16` `BYR2` | 16-bit raw Bayer, little-endian | assigned |
| `GREY` `Y10P` `Y12P` `Y16 ` | monochrome, 8/10/12/16-bit | assigned |

Where a V4L2 fourcc exists for a payload, it is used verbatim — the format
then has an external authority and needs no definition here. A payload with no
V4L2 code is assigned one in this table, by an issue against this repository.
**Experimental payloads MUST use a fourcc whose first byte is `X`**; those are
never registered and never collide with an assignment.

## Known implementations

| Implementation | Role | Status |
| --- | --- | --- |
| [`picam2hdmi`](https://github.com/bayerlink/picam2hdmi) | encoder — Raspberry Pi, every libcamera sensor | reference encoder; patterns, container and KMS scanout implemented, awaiting the first on-target run |
| [`np2hw.bayerlink_in`](https://github.com/lanserge/np2hw) | decoder — parallel video in, elastic 12-bit stream out, for FPGA receivers | **working** — bit-exact against the reference codec in simulation; the protocol's first independent implementation |
| [`bayertap`](https://github.com/bayerlink/bayertap) | decoder — passive conformance tap: any V4L2 capture device, lane probing, pattern judging, the luma tunnel for Y-only dongles | **working** off-target; meets capture silicon at the bench |
| Microcontroller pattern dongle (RP2350/HSTX) | encoder — receiver bring-up with no camera; DVP-class sensors via the RAW8 fourccs | anticipated |
| Jetson tool | encoder — MIPI sensors beyond the Pi's ecosystem | anticipated |

To be listed: implement the spec, pass the vectors, open an issue.
