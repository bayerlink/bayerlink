"""The luma tunnel: bayerlink through a channel that only preserves Y.

EXPERIMENTAL TRANSPORT SHIM, not part of the wire protocol. The conformance
vectors do not cover it, and a receiver needs no knowledge of it to be
conformant. It exists for one bench reality: the cheapest capture hardware
(USB2 UVC dongles) delivers YUY2 -- an RGB-to-YCbCr matrix plus 4:2:2 chroma
subsampling -- which destroys a byte container. What that channel preserves
is the full-resolution luma plane, to within an affine map (a possible
16..235 range squeeze) and rounding.

An affine map plus bounded noise is not an obstacle; it is a channel, and
this module modulates through it:

  NIBBLES AS GRAY   the source draws greyscale only (R = G = B), one nibble
      per display pixel as one of 16 levels spaced 17 apart -- an order of
      magnitude above any sane converter's rounding error. Grey makes the
      chroma constant, so subsampling destroys nothing.

  A PILOT LINE      physical row 0 carries the 16 levels in a known repeating
      ramp. The decoder measures what each level actually arrived as and
      classifies payload pixels against those LEARNED centroids -- so the
      channel's exact matrix, range and rounding never need to be known.

Underneath, the container is UNCHANGED: encode wraps a normal bayerlink
container (built for a virtual, narrower display), decode hands back that
container for the ordinary decode_frame(). Capacity costs 6x (one byte
becomes two pixels of three channels), which a conformance bench does not
care about: it needs bytes proven exact, not throughput.

Layout, fixed by this module for both ends:

  physical row 0                pilot: level (x % 16) across the used width
  physical rows 1..inner_h      inner container row r-1, each byte as two
                                pixels, high nibble first
  remaining rows / pixels       zero

The inner container width is ``phys_width // 6`` (three bytes per inner
pixel, two physical pixels per byte).
"""
from __future__ import annotations

import numpy as np

LEVELS = 16
STEP = 255 // (LEVELS - 1)          # 17: levels are 0, 17, ... 255 exactly


def inner_display(phys_width: int, phys_height: int) -> tuple[int, int]:
    """The virtual display a container must be encoded for, to fit the tunnel."""
    if phys_width < 6 * 11:
        raise ValueError(
            f"a {phys_width}-pixel tunnel cannot carry the minimum container "
            "width (11 inner pixels = 66 physical)")
    return phys_width // 6, phys_height - 1


def encode(container: np.ndarray, phys: tuple[int, int]) -> np.ndarray:
    """A bayerlink container -> the greyscale frame to scan out.

    ``container`` is (inner_h, inner_w, 3) uint8, encoded for
    ``inner_display(*phys)``. Returns (phys_h, phys_w, 3) uint8 with
    R = G = B everywhere -- ready for the ordinary scanout path.
    """
    phys_width, phys_height = phys
    inner_w, max_h = inner_display(phys_width, phys_height)
    height, width, channels = container.shape
    if channels != 3 or width != inner_w or height > max_h:
        raise ValueError(
            f"container {container.shape} does not fit a {phys} tunnel; "
            f"encode it for display=({inner_w}, <= {max_h})")

    used = inner_w * 6
    grey = np.zeros((phys_height, phys_width), np.uint8)
    grey[0, :used] = (np.arange(used) % LEVELS) * STEP          # pilot
    line_bytes = container.reshape(height, width * 3)
    nibbles = np.empty((height, used), np.uint8)
    nibbles[:, 0::2] = line_bytes >> 4                          # high first
    nibbles[:, 1::2] = line_bytes & 0xF
    grey[1:1 + height, :used] = nibbles * STEP
    return np.repeat(grey[:, :, None], 3, axis=2)


def decode(luma: np.ndarray, inner_height: int) -> np.ndarray:
    """A captured luma plane -> the inner container, classified per pilot.

    ``luma`` is (phys_h, phys_w) of anything integer-like -- the Y plane of a
    YUY2 capture, or one channel of an RGB one. ``inner_height`` is the
    inner container's height (its geometry is the receiver's configuration,
    exactly as in the direct path). Raises when the pilot is unreadable or
    ambiguous, because a tunnel that guesses is a tunnel that lies.
    """
    luma = np.asarray(luma)
    if luma.ndim != 2:
        raise ValueError(f"expected a (height, width) luma plane, got {luma.shape}")
    phys_height, phys_width = luma.shape
    inner_w, max_h = inner_display(phys_width, phys_height)
    if inner_height > max_h:
        raise ValueError(f"inner height {inner_height} cannot fit {luma.shape}")
    used = inner_w * 6

    # Learn what each of the 16 levels became: median per residue class of
    # the pilot row. Median, not mean -- a few corrupted pixels must not
    # drag a centroid.
    pilot = luma[0, :used].astype(np.int32)
    centroids = np.empty(LEVELS, np.int32)
    for level in range(LEVELS):
        centroids[level] = int(np.median(pilot[level::LEVELS]))
    order = np.diff(centroids)
    if not (order > 0).all():
        raise ValueError(
            "pilot centroids are not strictly increasing: the channel is not "
            "a monotonic map of luma (wrong line captured, scaling, or not a "
            f"tunnel frame). Learned: {centroids.tolist()}")
    if int(order.min()) < 4:
        raise ValueError(
            f"pilot levels are only {int(order.min())} counts apart; the "
            "channel is too noisy or too compressed to classify nibbles "
            "safely. Refusing beats returning plausible wrong bytes.")

    payload = luma[1:1 + inner_height, :used].astype(np.int32)
    # Nearest centroid via midpoint thresholds -- one searchsorted, no loops.
    thresholds = (centroids[:-1] + centroids[1:] + 1) // 2
    nibbles = np.searchsorted(thresholds, payload.ravel(),
                              side="right").astype(np.uint8)
    nibbles = nibbles.reshape(inner_height, used)
    line_bytes = (nibbles[:, 0::2] << 4) | nibbles[:, 1::2]
    return line_bytes.reshape(inner_height, inner_w, 3)
