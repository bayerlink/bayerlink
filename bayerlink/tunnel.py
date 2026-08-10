"""The luma tunnel: bayerlink through a channel that only preserves Y.

EXPERIMENTAL TRANSPORT SHIM, not part of the wire protocol. The conformance
vectors do not cover it, and a receiver needs no knowledge of it to be
conformant. It exists for one bench reality: the cheapest capture hardware
(USB2 UVC dongles) delivers YUY2, and what such a channel preserves is the
full-resolution luma plane -- to within everything the first real stick on
the bench actually applied: an S-shaped contrast curve, clipping above the
studio-swing ceiling, a small horizontal FIR, and a two-pixel delay. None
of that is an obstacle; it is a channel, and this module modulates through
it on three principles measured against that hardware:

  EIGHT LEVELS IN 16..196   full-swing tops are what a limited-range
      interpretation clips -- the measured MS2109-class expansion
      saturates from about input 200 -- and sixteen levels left the
      worst measured sample eleven counts from a midpoint eight away.
      Eight levels put every midpoint sixteen counts out: the whole
      observed error tail fits with room to spare, and the pilot still
      learns whatever curve remains.

  A TRIANGLE PILOT        physical row 0 sweeps the 16 levels up and back
      down -- no cliff anywhere, so the channel's low-pass has no
      discontinuity to smear into neighbouring levels. The decoder learns
      each level's arrival value AND the channel's horizontal delay from
      the same row: the fold offset that yields a strictly monotone
      staircase is the delay, unique below one pilot period.

  FIVE-PIXEL CELLS        every nibble is painted five times and read
      at its CENTRE pixel, which sits two own-valued pixels away from
      anything foreign -- the measured low-pass has ~2-3 px of support,
      and the margin is spent on noise, not on neighbours.

Underneath, the container is UNCHANGED: encode wraps a normal bayerlink
container (built for a virtual, narrower display), decode hands back that
container for the ordinary decode_frame(). Capacity costs 40x (three
bytes become eight cells of five pixels, of three channels), which a conformance bench does not
care about: it needs bytes proven exact, not throughput.

Layout, fixed by this module for both ends:

  physical row 0                pilot: the triangle level sequence
                                0,1,..,7,6,..,1 as 5-px cells (70-px
                                period) across the used width
  physical rows 1..inner_h      inner container row r-1, its bytes as a
                                bit stream, three bits per 5-px cell,
                                most significant bits first
  remaining rows / pixels       zero

The inner container width is ``phys_width // 40`` (three bytes per inner
pixel, eight cells per three bytes, five pixels per cell).
"""
from __future__ import annotations

import numpy as np

LEVELS = 8
CELL = 5                              # physical pixels per 3-bit cell
# The constellation stays below the measured saturation knee (~200 on
# MS2109-class expansion), not merely below the textbook 235.
LEVEL_VALUES = np.round(np.linspace(16.0, 196.0, LEVELS)).astype(np.uint8)
# Pilot cell sequence: a triangle, cliff-free by construction.
PILOT = np.concatenate([np.arange(LEVELS),
                        np.arange(LEVELS - 2, 0, -1)])       # 30 cells
PILOT_PERIOD_PX = PILOT.size * CELL                          # 60 px


def inner_display(phys_width: int, phys_height: int) -> tuple[int, int]:
    """The virtual display a container must be encoded for, to fit the tunnel."""
    if phys_width < 40 * 11:
        raise ValueError(
            f"a {phys_width}-pixel tunnel cannot carry the minimum container "
            "width (11 inner pixels = 440 physical)")
    return phys_width // 40, phys_height - 1


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

    cells = inner_w * 8                     # 3-bit cells per line
    used = cells * CELL
    grey = np.zeros((phys_height, phys_width), np.uint8)

    pilot_cells = PILOT[np.arange(cells) % PILOT.size]
    grey[0, :used] = np.repeat(LEVEL_VALUES[pilot_cells], CELL)

    line_bytes = container.reshape(height, width * 3)
    bits = np.unpackbits(line_bytes, axis=1)
    groups = bits.reshape(height, cells, 3)
    values = (groups[:, :, 0] << 2) | (groups[:, :, 1] << 1) | groups[:, :, 2]
    grey[1:1 + height, :used] = np.repeat(LEVEL_VALUES[values], CELL, axis=1)
    return np.repeat(grey[:, :, None], 3, axis=2)


def decode(luma: np.ndarray, inner_height: int) -> np.ndarray:
    """A captured luma plane -> the inner container, classified per pilot.

    ``luma`` is (phys_h, phys_w) of anything integer-like. ``inner_height``
    is the inner container's height (its geometry is the receiver's
    configuration, exactly as in the direct path). Raises when the pilot is
    unreadable or ambiguous, because a tunnel that guesses is a tunnel that
    lies.
    """
    luma = np.asarray(luma)
    if luma.ndim != 2:
        raise ValueError(f"expected a (height, width) luma plane, got {luma.shape}")
    phys_height, phys_width = luma.shape
    inner_w, max_h = inner_display(phys_width, phys_height)
    if inner_height > max_h:
        raise ValueError(f"inner height {inner_height} cannot fit {luma.shape}")
    cells = inner_w * 8

    def cell_reads(row, delay):
        """Each cell's centre pixel at a candidate delay; cells that fall
        off the frame edge read 0 and are reported invalid."""
        centre = delay + CELL * np.arange(cells) + CELL // 2
        valid = (centre >= 0) & (centre < phys_width)
        reads = np.zeros(cells, np.int32)
        reads[valid] = row[centre[valid]]
        return reads, valid

    # Learn the channel from the pilot: for every candidate delay, read
    # each cell's mean and take the median arrival value per level. The
    # delay whose staircase is strictly increasing IS the channel's delay.
    pilot_row = luma[0].astype(np.int32)
    pilot_levels = PILOT[np.arange(cells) % PILOT.size]
    candidates = []
    # Delays are searched within a quarter pilot period: generous for any
    # real capture pipeline, and it keeps an INVERTED channel from aliasing
    # -- the triangle is symmetric, so inversion looks like a half-period
    # shift, which this range can never reach.
    quarter = PILOT_PERIOD_PX // 4
    for delay in range(-quarter, quarter):
        reads, valid = cell_reads(pilot_row, delay)
        if valid.sum() < cells // 2:
            continue
        samples = reads[valid]
        levels_here = pilot_levels[valid]
        folded = np.empty(LEVELS, np.int32)
        spread = 0.0
        for level in range(LEVELS):
            member = samples[levels_here == level]
            folded[level] = int(np.median(member))
            spread = max(spread, float(
                np.median(np.abs(member - folded[level]))))
        steps = np.diff(folded)
        if (steps > 0).all() and int(steps.min()) >= 4:
            candidates.append((delay, folded, int(steps.min()), spread))
    if not candidates:
        zero_means, _ = cell_reads(pilot_row, 0)
        zero = [int(np.median(zero_means[pilot_levels == level]))
                for level in range(LEVELS)]
        raise ValueError(
            "pilot centroids are not strictly increasing (with usable "
            "gaps) at any delay: the channel is not a monotonic map of "
            "luma (wrong line captured, scaling, or not a tunnel frame). "
            f"Learned at delay 0: {zero}")
    # Delays within one cell all read that cell's value (give or take
    # the FIR at its edge pixels), so the tight candidates form one
    # CONSECUTIVE RUN per true alignment -- and the run's middle is the
    # cell centre. A second run elsewhere would mean two competing
    # alignments, which no honest channel produces.
    tightest = min(c[3] for c in candidates)
    strong = sorted(c for c in candidates if c[3] <= 2 * tightest + 2)
    delays = [c[0] for c in strong]
    if delays[-1] - delays[0] >= CELL or len(delays) != len(
            range(delays[0], delays[-1] + 1)):
        raise ValueError(
            f"pilot is ambiguous: delays {delays} fold with comparable "
            "tightness but do not agree on one cell. Refusing beats "
            "guessing which alignment lies.")
    delay, centroids, gap, spread = strong[len(strong) // 2]
    if gap < 4:
        raise ValueError(
            f"pilot levels are only {gap} counts apart; the channel is too "
            "noisy or too compressed to classify nibbles safely. Refusing "
            "beats returning plausible wrong bytes.")
    # Read every payload cell's CENTRE pixel at the learned delay -- the
    # same read the pilot was learned from. Cells a delay pushes past the
    # frame edge are gone physically; they read as level 0 and are left
    # for the container's own checks to judge -- which is why a source
    # should not fill the tunnel to its last byte.
    centre = delay + CELL * np.arange(cells) + CELL // 2
    valid = (centre >= 0) & (centre < phys_width)
    rows = luma[1:1 + inner_height].astype(np.int32)
    sampled = np.zeros((inner_height, cells), np.int32)
    sampled[:, valid] = rows[:, centre[valid]]

    thresholds = (centroids[:-1] + centroids[1:] + 1) // 2
    values = np.searchsorted(thresholds, sampled.ravel(),
                             side="right").astype(np.uint8)
    values = values.reshape(inner_height, cells)
    bits = np.empty((inner_height, cells, 3), np.uint8)
    bits[:, :, 0] = values >> 2
    bits[:, :, 1] = (values >> 1) & 1
    bits[:, :, 2] = values & 1
    line_bytes = np.packbits(bits.reshape(inner_height, cells * 3), axis=1)
    return line_bytes.reshape(inner_height, inner_w, 3)
