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
    #
    # The channel may also DELAY the line by a few pixels -- real capture
    # sticks do -- which shifts every cell right by the same amount. The
    # pilot learns that too: fold it at every offset, and the one offset
    # whose staircase is strictly increasing IS the delay, unique by
    # construction for delays smaller than one pilot period. A channel
    # property never needs to be configured when a pilot can measure it.
    pilot = luma[0, :used].astype(np.int32)
    candidates = []
    for shift in range(LEVELS):
        folded = np.empty(LEVELS, np.int32)
        for level in range(LEVELS):
            folded[level] = int(np.median(
                pilot[(level + shift) % LEVELS::LEVELS]))
        steps = np.diff(folded)
        if (steps > 0).all():
            candidates.append((shift, folded, int(steps.min())))
    if not candidates:
        zero_fold = [int(np.median(pilot[level::LEVELS]))
                     for level in range(LEVELS)]
        raise ValueError(
            "pilot centroids are not strictly increasing at any delay: the "
            "channel is not a monotonic map of luma (wrong line captured, "
            f"scaling, or not a tunnel frame). Learned at delay 0: {zero_fold}")
    if len(candidates) > 1:
        raise ValueError(
            f"pilot is ambiguous: {len(candidates)} delays fold to a "
            "monotonic staircase. Refusing beats guessing which one lies.")
    shift, centroids, gap = candidates[0]
    if gap < 4:
        raise ValueError(
            f"pilot levels are only {gap} counts apart; the channel is too "
            "noisy or too compressed to classify nibbles safely. Refusing "
            "beats returning plausible wrong bytes.")

    # Undo the delay: content for column x arrived at column x + delay.
    # Delays past the frame edge lose those columns physically; they are
    # padded as zeros and left for the container's own checks to judge --
    # which is why a source should not fill the tunnel to its last byte.
    delay = shift if shift < LEVELS // 2 else shift - LEVELS
    rows = luma[1:1 + inner_height].astype(np.int32)
    if delay >= 0:
        payload = rows[:, delay:delay + used]
    else:
        payload = rows[:, :max(0, used + delay)]
        payload = np.pad(payload, ((0, 0), (-delay, 0)))
    if payload.shape[1] < used:
        payload = np.pad(payload, ((0, 0), (0, used - payload.shape[1])))
    # Nearest centroid via midpoint thresholds -- one searchsorted, no loops.
    thresholds = (centroids[:-1] + centroids[1:] + 1) // 2
    nibbles = np.searchsorted(thresholds, payload.ravel(),
                              side="right").astype(np.uint8)
    nibbles = nibbles.reshape(inner_height, used)
    line_bytes = (nibbles[:, 0::2] << 4) | nibbles[:, 1::2]
    return line_bytes.reshape(inner_height, inner_w, 3)
