# Changelog

Notable changes to the bayerlink reference library. The wire format
itself is specified in [PROTOCOL.md](PROTOCOL.md); this file records what
the *library* did, and calls out anything a caller has to change.

Pre-1.0, so the API can still move. Anything that moves is named here.

## 0.5.0

### Added

- **`bayerlink.recording`** — reading and writing a recording is now this
  library's job. Three repositories had grown their own idea of what a
  recorded frame is: the source that writes them, the receiver toolbox
  that replays them, and an instrument that had started guessing shapes.
  A recording is the wire, kept, so the library that owns the wire owns
  it. Callers doing their own `np.load` and shape-sniffing should use
  this instead.

### Removed

- **The luma tunnel** (`bayerlink.tunnel`), and the `FLAG_LUMA_TUNNEL`
  path with it. **Breaking** for anyone importing it, though nothing is
  known to.

  It existed because the cheapest capture hardware throws away colour:
  containers encoded as grey levels with a pilot line that learned the
  stick's level curve, recovering bytes exactly at forty times the
  capacity. That bought byte-level proof of a real link months before
  there was an FPGA to receive one. There is one now, and the tunnel has
  not carried a frame since — while leaving behind a whole codec, a wire
  format nobody transmits, a flag, and two geometry budgets that every
  crop calculation had to branch on.

  The bench evidence is not lost: the 2026-08-10 MS2109 session and its
  capacity arithmetic are in the history that added it, should Y-only
  capture ever be worth paying for again.

- **The sensor-model registry behind `source_id`.** Retired before it was
  ever published, so no index has to live with it.

### Changed

- **`source_id` means what the spec always said it meant**: it indexes
  the sources on a device — 0, 1, 2 in the order presented, and 0 on a
  device with one sensor, which is most of them. *"source_id
  distinguishes CAMERAS, not links: a stereo pair is two sources."*

  The registry layered on top carried its own refutation: two cameras of
  the same model are two sources and one model, so a model-derived value
  cannot do the one job the field has, and its own comment advised
  overriding it by hand. A field whose default defeats its purpose is not
  a default. Its rationale is spent besides — a receiver's calibration is
  now pushed by whoever owns the sensor, over the link's register
  channel, which knows the sensor exactly rather than inferring it.

- **The version has one owner**, the packaging metadata. It was written
  in two places, which is one place too many for a number every consumer
  reads.

### Internal

- Every source file carries its copyright and SPDX identifier, checked
  mechanically — including `vectors/`, which was outside the checked
  roots and so had its header by hand rather than by verification. The
  identifier is read from `pyproject.toml`, never restated, so the check
  cannot drift from what is published.
