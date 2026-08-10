# Practical guide

Route by what is on your desk. Every command here is run as written on
real hardware.

| You have | Go to |
| --- | --- |
| A Raspberry Pi and a camera | [1. The Pi as a raw source](#1-the-pi-as-a-raw-source) |
| An FPGA board with HDMI-in | [2. Receiving on an FPGA](#2-receiving-on-an-fpga) |
| A USB capture stick and no FPGA | [3. The no-FPGA bench](#3-the-no-fpga-bench) |
| A sensor that is not 12-bit Bayer | [4. Other formats: 8/10/14/16-bit, mono](#4-other-formats) |
| A stream to record, or a recording to replay | [5. Recording and replay](#5-recording-and-replay) |
| A codebase in another language | [6. Implementing the protocol yourself](#6-implementing-it-yourself) |

Whatever the path, one rule governs the link itself: **full-range RGB,
no scaling, no overscan, 4:4:4**. A limited-range clamp (16–235) is the
single most common integration failure, and the `checker` and `corners`
test patterns exist to catch it on day one.

## 1. The Pi as a raw source

[`picam2hdmi`](https://github.com/bayerlink/picam2hdmi) turns a Pi into a
sensor module with an HDMI plug — its
[SETUP.md](https://github.com/bayerlink/picam2hdmi/blob/main/SETUP.md) is
the step-by-step from blank SD card to streaming instrument. On a fresh
Raspberry Pi OS **Lite** (no desktop — the streamer must own the display):

```sh
sudo pip3 install --break-system-packages picam2hdmi
sudo picam2hdmi stream --source pattern --pattern counting \
    --width 512 --height 240 --bayer RGGB --mode 1920x1080@30
```

That is a receiver bring-up source with no camera attached: deterministic
patterns, self-described by the header line. With a camera attached,
`--source camera` streams the sensor's own packed raw -- order and depth
taken from libcamera's report, AE/AWB off by default (a raw source is
deterministic; set `--exposure-us` and `--gain` yourself), and `--crop
x,y,w,h` selects a window: how a big sensor meets the link budget, and
how a small window fits the luma tunnel for byte-level verification.

For a permanent bench, run it as an INSTRUMENT — `picam2hdmi serve`
(systemd unit in `contrib/`) streams from power-on and takes control
over HTTP, so a test rig can drive the physical bench unattended:

```sh
curl http://picam.local:8080/status
curl -X PUT http://picam.local:8080/source \
     -d '{"source":"pattern","pattern":"checker","width":512,"height":240,"bayer":"RGGB"}'
curl -T session.npy http://picam.local:8080/recordings/session.npy
curl -X PUT http://picam.local:8080/source -d '{"source":"file","file":"session.npy"}'
```

A LAN bench instrument, not an internet service — bind and firewall
accordingly. Refusals arrive as HTTP 400 carrying the same named errors
the CLI prints.

Sizing: a container of N display lines carries at most N−1 camera lines
(the header costs one), and the receiver rate rule is
`camera_width <= total line slots of the display mode` — 2028-sample
lines fit 1080p (2200 slots), not 720p (1650). Leave end-of-line slack:
a link that delays the line by a few pixels loses the last columns, so
never fill the container to its final byte.

## 2. Receiving on an FPGA

Two options:

- **Use the working decoder.** `np2hw.bayerlink_in` (in
  [np2hw](https://github.com/lanserge/np2hw)) is a generated Verilog
  receiver: parallel video in, one elastic 12-bit sample per clock out,
  two-bank half-line FIFO, sticky overflow flag, byte-lane remapping. It
  is held bit-exact against this repository's codec by np2hw's example
  suite.
- **Write your own** from [PROTOCOL.md](PROTOCOL.md), and prove it
  against [`vectors/`](vectors/) — the committed bytes are the
  conformance claim, so your implementation never has to run this one.
  The header line may be skipped in hardware (configure the receiver's
  geometry, validate headers on the host); that is exactly what
  `bayerlink_in` does.

Byte-lane order varies per platform pair. Do not resolve it with a
scope: capture any frame and let `detect_lane_map()` (or
`bayertap probe`) try all six permutations against the header's magic
and CRC.

## 3. The no-FPGA bench

Any UVC capture device closes the loop; what changes is how much of the
byte container survives its pipeline:

| Device class | Path | What survives |
| --- | --- | --- |
| TC358743 bridge (Pi HDMI-to-CSI boards) | `--via direct` | bytes, exactly |
| MS2130S / MS2131S (USB3, ~$15) | `--via direct` | bytes, if the stick is transparent — `check` answers in minutes |
| MS2109-class (USB2, ~$10, YUY2-only) | `--via tunnel` | luma only — use the tunnel |

On Linux, [`bayertap`](https://github.com/bayerlink/bayertap) speaks to
the device directly:

```sh
bayertap probe                                    # resolve byte lanes
bayertap --via direct check --pattern counting    # judge the link
```

On macOS (no V4L2), grab through ffmpeg and check from the file:

```sh
python3 contrib/macgrab.py --device "USB Video" --mode tunnel --fps 5 --out grab.npy
bayertap --from-file grab.npy --via tunnel check --pattern counting
```

Address the stick by **name**, not index — it re-enumerates when the
HDMI signal drops. Prefer a low `--fps`: cheap sticks switch to MJPEG
(with its artifacts) at rates USB2 cannot carry raw.

For the MS2109 tunnel, the source wraps the container
(`picam2hdmi stream --luma-tunnel`) and pays 40x capacity for exactness:
inside a 1080p mode that is a camera of up to 48 x 1078 *bytes* per
line — pick something like `--width 88 --height 240`. The tunnel's
pilot line learns the stick's level curve and line delay by itself;
when it cannot classify safely, it refuses with the measurement in the
message rather than returning plausible wrong bytes.

## 4. Other formats

The fourcc names the payload, V4L2's names verbatim; the header never
changes shape. Supported today, in the reference codec and the vectors:

- **Bayer** at 8, 10, 12, 14, 16 bits (CSI-2 packed families; 16-bit
  little-endian) — `fourcc_for("RGGB", 10)` → `pRAA`.
- **Monochrome** at 8/10/12/16 (`GREY`, `Y10P`, `Y12P`, `Y16 `) —
  `fourcc_for(None, 8)`. Same container; there is simply no CFA phase.
  This also covers ToF modules that deliver phase images as mono raw.

A receiver implements the families it needs and refuses the rest by
fourcc — 12-bit packed Bayer is the mandatory baseline. Encoding at a
depth is one argument: `encode_frame(raw, "RGGB", seq, bits=10)`.

## 5. Recording and replay

A recording is the wire itself: a ``.npy`` stack of containers,
``(n, h, w, 3) uint8`` -- every frame still carries its own header, so
the file needs no schema of its own, and receivers already ignore
timing (they deduplicate by ``frame_seq``), so replay pacing is
non-semantic by construction.

```sh
bayertap --via direct save --out session.npy --frames 100   # record
bayertap --from-file session.npy --via direct check          # replay into the tools
sudo picam2hdmi stream --source file --file session.npy \
     --mode 1920x1080@30                                     # replay onto the wire
```

The wire replay loops forever and re-stamps ``frame_seq`` like a live
source (``--no-restamp`` preserves the recorded numbers for forensics).
Physical captures record the same way -- ``macgrab.py --frames N``
stacks what the stick delivered, channel damage included -- so a field
failure is captured once and debugged forever. Do not reach for a video
container format here: colorspace tags, range flags and
scaling-tolerant players are precisely the machinery that destroys byte
containers.

## 6. Implementing it yourself

[PROTOCOL.md](PROTOCOL.md) is the specification; this package is its
reference implementation; [`vectors/`](vectors/) pins the exact bytes of
valid containers across payload families and the striping rules. An
implementation in any language conforms when it produces those bytes
(encoder) or recovers pattern and header from them exactly (decoder).
Say "speaks bayerlink v2" when you do — see
[TRADEMARK.md](TRADEMARK.md) for the one thing the name asks.

Questions, or a device that does not fit this page:
**s.rabykin@gmail.com**, or an issue on this repository.
