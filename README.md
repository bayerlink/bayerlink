# bayerlink

**Raw sensor data over an HDMI/DVI link.**

FPGA boards rarely have camera connectors; nearly everything has HDMI. The
bayerlink protocol treats a display link's active area as a byte container:
packed raw Bayer samples, one camera line per display line, self-described by
a 48-byte header (magic, version, V4L2 fourcc, geometry, frame counter,
stripe and source identity for multi-link use, CRC).
Real sensor data into any board with HDMI-in — no MIPI hardware, no
deserialisers, no per-sensor bring-up on the receiver.

**New here? [GUIDE.md](GUIDE.md) routes by what is on your desk** — a Pi,
an FPGA board, a $10 capture stick, a sensor that is not 12-bit.

**[PROTOCOL.md](PROTOCOL.md) is the specification.** This package is its
reference implementation, and `vectors/` pins the exact bytes, so a
conforming implementation in any language never has to run this one.

Independent implementations are unrestricted and encouraged; say "speaks
bayerlink v2" and you are conforming, not licensing. See
[TRADEMARK.md](TRADEMARK.md) for the one thing the name asks of you.

## The package

```python
import bayerlink

frame = bayerlink.encode_frame(raw, "RGGB", frame_seq=7)   # (H, W, 3) uint8 out
header, raw = bayerlink.decode_frame(captured)              # and back
header.bayer_order, header.width, header.frame_seq
```

It runs on **both ends**: encoders build containers with it, and a receiver's
host software decodes captured frames with the same module — one
implementation to disagree with the spec, which is the fewest possible.

`bayerlink.pattern` carries the link-proving test patterns (`counting`,
`gradient`, `checker`, `corners`) every encoder and receiver bring-up uses;
`checker` and `corners` pin 0 and full scale, the first casualties of a
limited-range link.

## Implementations

The registry lives at the end of [PROTOCOL.md](PROTOCOL.md). Reference
encoder: [picam2hdmi](https://github.com/bayerlink/picam2hdmi) (Raspberry Pi,
every libcamera sensor). To be listed: implement the spec, pass the vectors,
open an issue.

## Funding

Developed independently; recurring support via
[github.com/sponsors/lanserge](https://github.com/sponsors/lanserge), or write
first: **s.rabykin@gmail.com**. Sponsorable capability targets carry the
`sponsorable` label on the issue tracker — currently the
[PiSP compressed payload family](https://github.com/bayerlink/bayerlink/issues/1)
(Pi 5 sources at ~1 byte/sample). Scope is agreed in writing before work
starts; sponsored work lands in the open tree immediately, licensed like
everything else — sponsorship buys ordering and named credit, not
exclusivity. The person behind it:
[serge.rabyking.com](https://serge.rabyking.com).

## Licence

Apache-2.0 — chosen over MIT for two of its clauses, not for anything this
project owns. Section 3 means every contributor grants implementers a licence
to any patent claims their contribution would infringe: no such patents are
known or claimed, and the clause is insurance FOR implementers, not an
assertion by this project. Section 6 makes explicit that the licence covers
the text and code, never the name (see TRADEMARK.md). A protocol meant for many independent implementers benefits
from both being written down.
