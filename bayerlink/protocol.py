"""bayerlink v2: the reference implementation of PROTOCOL.md.

This module IS the executable form of the specification, and it lives in the
protocol's own repository so that every encoder and every receiver -- the Pi
tool, a microcontroller dongle, an FPGA decoder's host software -- tests
against ONE implementation. Encoding produces a byte container any scanout can
carry; decoding accepts a byte container any capture produced; the committed
vectors under vectors/ pin the exact bytes, so an implementation in any
language can conform without running this one.
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

import numpy as np

MAGIC = 0x4B4C5942            # the bytes "BYLK", little-endian
VERSION = 2
HEADER_BYTES = 48
_HEADER_FMT = "<IHHIIIIIBBBBIII"   # magic, version, header_bytes, fourcc,
                                   # width, height, frame_seq, flags,
                                   # source_id, stripe_index, stripe_count,
                                   # reserved, stripe_offset, full_height,
                                   # reserved2

FLAG_TEST_PATTERN = 1 << 0
_KNOWN_FLAGS = FLAG_TEST_PATTERN

# V4L2 raw fourccs required by version 2: the 12-bit packed Bayer family.
# The fourcc encodes format, bit depth AND Bayer order in one field that
# already has an external authority defining it.
_FOURCC_12P = {
    "pRCC": "RGGB",
    "pgCC": "GRBG",
    "pGCC": "GBRG",
    "pBCC": "BGGR",
}
_ORDER_TO_FOURCC = {order: code for code, order in _FOURCC_12P.items()}

# Bayer order -> the two phase bits revela-style pipelines consume:
# bit 1 = row parity of R, bit 0 = column parity of R.
BAYER_PHASE = {"RGGB": 0b00, "GRBG": 0b01, "GBRG": 0b10, "BGGR": 0b11}


def fourcc_code(text: str) -> int:
    """The u32 a four-character code occupies, little-endian."""
    if len(text) != 4:
        raise ValueError(f"a fourcc is four characters, got {text!r}")
    return int.from_bytes(text.encode("ascii"), "little")


def fourcc_text(code: int) -> str:
    return int(code).to_bytes(4, "little").decode("ascii", errors="replace")


def fourcc_for(order: str, bits: int = 12) -> str:
    """The fourcc for a Bayer order at a bit depth version 1 carries."""
    if bits != 12:
        raise ValueError(
            f"bayerlink v2 requires the 12-bit packed family; {bits}-bit payloads "
            "are a future fourcc, not a variation of this one")
    try:
        return _ORDER_TO_FOURCC[order.upper()]
    except KeyError:
        raise ValueError(
            f"unknown Bayer order {order!r}; expected one of "
            f"{sorted(_ORDER_TO_FOURCC)}") from None


# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Header:
    """The 48 bytes at the start of line 0, parsed and validated.

    ``height`` is the payload lines THIS stream carries -- a stripe's band
    when the frame travels over several links, or the whole frame when it
    does not. ``full_height`` is the whole frame either way, and the stripe
    fields say which slice this is; ``source_id`` says which camera, so two
    independent streams are never mistaken for stripes of each other.
    Identity travels in-band -- pairing never depends on which capture
    device a frame happened to arrive through.
    """

    fourcc: str
    width: int
    height: int
    frame_seq: int
    flags: int = 0
    source_id: int = 0
    stripe_index: int = 0
    stripe_count: int = 1
    stripe_offset: int = 0
    full_height: int = 0          # 0 -> normalised to height (unstriped)
    version: int = VERSION

    def __post_init__(self):
        if self.full_height == 0:
            object.__setattr__(self, "full_height", self.height)
        if not 1 <= self.stripe_count <= 255:
            raise ValueError(f"stripe_count {self.stripe_count} outside 1..255")
        if not 0 <= self.stripe_index < self.stripe_count:
            raise ValueError(
                f"stripe_index {self.stripe_index} outside this frame's "
                f"{self.stripe_count} stripe(s)")
        if not 0 <= self.source_id <= 255:
            raise ValueError(f"source_id {self.source_id} outside u8")
        if self.stripe_count == 1:
            if self.stripe_offset != 0 or self.full_height != self.height:
                raise ValueError(
                    "an unstriped stream must have stripe_offset 0 and "
                    f"full_height == height; got offset {self.stripe_offset}, "
                    f"full_height {self.full_height}, height {self.height}")
        else:
            if self.stripe_offset % 2 or self.height % 2:
                raise ValueError(
                    "stripe boundaries must land on even camera lines -- an "
                    "odd offset or band flips the CFA phase mid-frame, which "
                    "presents as a demosaic bug two projects downstream; got "
                    f"offset {self.stripe_offset}, band {self.height}")
            if self.stripe_offset + self.height > self.full_height:
                raise ValueError(
                    f"stripe [{self.stripe_offset}, "
                    f"{self.stripe_offset + self.height}) exceeds the "
                    f"{self.full_height}-line frame")

    @property
    def bayer_order(self) -> str:
        return _FOURCC_12P[self.fourcc]

    @property
    def bayer_phase(self) -> int:
        return BAYER_PHASE[self.bayer_order]

    @property
    def bits(self) -> int:
        return 12

    @property
    def line_bytes(self) -> int:
        return self.width * 3 // 2

    @property
    def is_test_pattern(self) -> bool:
        return bool(self.flags & FLAG_TEST_PATTERN)

    def pack(self) -> bytes:
        body = struct.pack(
            _HEADER_FMT, MAGIC, self.version, HEADER_BYTES,
            fourcc_code(self.fourcc), self.width, self.height,
            self.frame_seq, self.flags, self.source_id, self.stripe_index,
            self.stripe_count, 0, self.stripe_offset, self.full_height, 0)
        return body + struct.pack("<I", zlib.crc32(body))

    @classmethod
    def unpack(cls, raw: bytes) -> "Header":
        """Parse and VERIFY a header. Refusal is the API: no guessed decodes."""
        if len(raw) < HEADER_BYTES:
            raise ValueError(f"header needs {HEADER_BYTES} bytes, got {len(raw)}")
        body, crc = raw[:44], struct.unpack("<I", raw[44:48])[0]
        (magic, version, header_bytes, code, width, height, frame_seq, flags,
         source_id, stripe_index, stripe_count, reserved,
         stripe_offset, full_height, reserved2) = struct.unpack(_HEADER_FMT, body)
        if magic != MAGIC:
            raise ValueError(
                f"not a bayerlink stream: magic {magic:#010x}, expected {MAGIC:#010x}. "
                "The usual causes are a limited-range or YCbCr link, or byte-lane "
                "permutation -- see PROTOCOL.md, 'Requirements on the link'.")
        if version != VERSION:
            # Checked BEFORE the CRC: version 1's CRC sits at byte 28, so a
            # v1 frame read as v2 would report "corrupt" -- wrong diagnosis.
            raise ValueError(
                f"bayerlink version {version} is not the {VERSION} this "
                "implementation speaks. Version 1 (32-byte header) is "
                "historical -- reference releases up to 0.2.0 -- with no "
                "deployed sources; anything newer needs a newer decoder.")
        if crc != zlib.crc32(body):
            raise ValueError(
                "header CRC mismatch: the magic survived but the header did not. "
                "Suspect a link that modifies pixel values (range clamp, dithering).")
        if header_bytes < HEADER_BYTES:
            raise ValueError(
                f"header_bytes {header_bytes} is shorter than v2's minimum")
        if reserved or reserved2:
            raise ValueError(
                "reserved header bytes are nonzero; they are must-be-zero in "
                "v2, and a sender setting them is speaking a future dialect "
                "this decoder would only misread")
        if flags & ~_KNOWN_FLAGS:
            raise ValueError(
                f"unknown flag bits {flags & ~_KNOWN_FLAGS:#x} set; v2 "
                "defines only bit 0 (test pattern), and unknown flags are "
                "refused rather than ignored")
        text = fourcc_text(code)
        if text not in _FOURCC_12P:
            raise ValueError(
                f"payload fourcc {text!r} is not implemented here; v1 requires "
                f"{sorted(_FOURCC_12P)}. Refusing a format beats decoding it wrongly.")
        if width <= 0 or width % 2:
            raise ValueError(f"width {width} must be positive and even for 12P")
        if height <= 0:
            raise ValueError(f"height {height} must be positive")
        return cls(fourcc=text, width=width, height=height,
                   frame_seq=frame_seq, flags=flags, source_id=source_id,
                   stripe_index=stripe_index, stripe_count=stripe_count,
                   stripe_offset=stripe_offset, full_height=full_height,
                   version=version)


# --------------------------------------------------------------------------- #
# 12-bit packed payload (V4L2 *12P)
# --------------------------------------------------------------------------- #

def pack12p(samples: np.ndarray) -> np.ndarray:
    """Samples (…, N even) uint16 -> packed bytes (…, N*3/2) uint8.

    Layout per pair P0, P1:  [ P0[11:4] ][ P1[11:4] ][ P1[3:0]<<4 | P0[3:0] ]
    """
    samples = np.asarray(samples)
    if samples.shape[-1] % 2:
        raise ValueError("12P packs sample PAIRS; the last axis must be even")
    if samples.dtype != np.uint16:
        raise TypeError(f"samples must be uint16, got {samples.dtype}")
    if int(samples.max(initial=0)) > 0xFFF:
        raise ValueError("a 12-bit sample exceeds 4095; refusing to truncate")
    p0 = samples[..., 0::2]
    p1 = samples[..., 1::2]
    out = np.empty(samples.shape[:-1] + (samples.shape[-1] * 3 // 2,), np.uint8)
    out[..., 0::3] = (p0 >> 4).astype(np.uint8)
    out[..., 1::3] = (p1 >> 4).astype(np.uint8)
    out[..., 2::3] = (((p1 & 0xF) << 4) | (p0 & 0xF)).astype(np.uint8)
    return out


def unpack12p(packed: np.ndarray) -> np.ndarray:
    """Inverse of :func:`pack12p`: bytes (…, M multiple of 3) -> uint16 samples."""
    packed = np.asarray(packed, dtype=np.uint8)
    if packed.shape[-1] % 3:
        raise ValueError("12P bytes come in triples; the last axis must divide by 3")
    b0 = packed[..., 0::3].astype(np.uint16)
    b1 = packed[..., 1::3].astype(np.uint16)
    b2 = packed[..., 2::3].astype(np.uint16)
    out = np.empty(packed.shape[:-1] + (packed.shape[-1] * 2 // 3,), np.uint16)
    out[..., 0::2] = (b0 << 4) | (b2 & 0xF)
    out[..., 1::2] = (b1 << 4) | (b2 >> 4)
    return out


# --------------------------------------------------------------------------- #
# Frame container
# --------------------------------------------------------------------------- #

def check_geometry(width: int, height: int, display: tuple[int, int]) -> None:
    """Refuse a camera mode the container cannot carry.

    ``display`` is (active_width, active_height) of the display mode. The line
    budget is bytes; the height budget loses one line to the header.
    """
    display_width, display_height = display
    if display_width * 3 < HEADER_BYTES:
        raise ValueError(
            f"a {display_width}-pixel-wide container cannot hold the "
            f"{HEADER_BYTES}-byte header line; the minimum width is "
            f"{-(-HEADER_BYTES // 3)} pixels")
    line_bytes = width * 3 // 2
    if line_bytes > display_width * 3:
        raise ValueError(
            f"{width} samples/line needs {line_bytes} bytes, but a "
            f"{display_width}-pixel display line carries {display_width * 3}")
    if height + 1 > display_height:
        raise ValueError(
            f"{height} camera lines + 1 header line exceed the "
            f"{display_height}-line display frame")


def fits_line_rate(width: int, total_line_slots: int) -> bool:
    """The one-sample-per-clock receiver budget (see PROTOCOL.md).

    True iff a receiver clocked at the display pixel clock keeps up with a
    small line FIFO: the camera line must fit in the WHOLE line time,
    blanking included. 2028 fits 1080p (2200 slots); it does not fit 720p
    (1650), and no FIFO depth fixes a violated average.
    """
    return width <= total_line_slots


def encode_frame(raw: np.ndarray, bayer_order: str, frame_seq: int,
                 display: tuple[int, int] = (1920, 1080),
                 flags: int = 0, source_id: int = 0,
                 stripe: tuple[int, int, int, int] | None = None) -> np.ndarray:
    """One camera frame -> the (height, width, 3) uint8 container to scan out.

    ``raw`` is (lines, samples) uint16, one camera line per row. The result is
    the display frame's memory image: header in line 0, one packed camera line
    per display line, zeros elsewhere.

    ``stripe`` is ``(index, count, offset, full_height)`` when ``raw`` is one
    band of a larger frame travelling over several links; most callers want
    :func:`encode_stripes`, which derives it.
    """
    raw = np.asarray(raw)
    if raw.ndim != 2:
        raise ValueError(f"raw frame must be (lines, samples), got {raw.shape}")
    height, width = raw.shape
    check_geometry(width, height, display)
    display_width, display_height = display

    index, count, offset, full = stripe if stripe else (0, 1, 0, height)
    header = Header(fourcc=fourcc_for(bayer_order), width=width, height=height,
                    frame_seq=frame_seq, flags=flags, source_id=source_id,
                    stripe_index=index, stripe_count=count,
                    stripe_offset=offset, full_height=full)
    frame = np.zeros((display_height, display_width * 3), np.uint8)
    frame[0, :HEADER_BYTES] = np.frombuffer(header.pack(), np.uint8)
    frame[1:1 + height, :header.line_bytes] = pack12p(raw.astype(np.uint16))
    return frame.reshape(display_height, display_width, 3)


def decode_frame(frame: np.ndarray) -> tuple[Header, np.ndarray]:
    """The inverse: a captured (height, width, 3) container -> (Header, raw).

    Runs on the RECEIVER's host, over whatever its capture path stored -- the
    same module that encoded the frame, so the two ends cannot drift apart.
    Raises rather than guessing on anything malformed; the error messages name
    the usual link-integrity suspects.
    """
    frame = np.asarray(frame, dtype=np.uint8)
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError(f"expected (height, width, 3) bytes, got {frame.shape}")
    lines = frame.reshape(frame.shape[0], frame.shape[1] * 3)
    header = Header.unpack(lines[0, :HEADER_BYTES].tobytes())
    if header.height + 1 > lines.shape[0]:
        raise ValueError(
            f"header claims {header.height} payload lines but the container "
            f"has {lines.shape[0] - 1}")
    payload = lines[1:1 + header.height, :header.line_bytes]
    return header, unpack12p(payload)


def split_stripes(height: int, stripes: int) -> list[tuple[int, int]]:
    """``(offset, band_height)`` per stripe: contiguous even bands, in order.

    Bands are even so every stripe boundary lands on a whole CFA row -- the
    rule the Header enforces -- and as equal as evenness allows, the earlier
    stripes taking the surplus.
    """
    if stripes < 1:
        raise ValueError(f"stripes {stripes} must be at least 1")
    if height % 2 or height < 2 * stripes:
        raise ValueError(
            f"{height} camera lines cannot split into {stripes} even bands; "
            "striping needs an even height of at least 2 lines per stripe")
    base = (height // stripes) & ~1
    surplus = (height - base * stripes) // 2
    bands, offset = [], 0
    for index in range(stripes):
        band = base + (2 if index < surplus else 0)
        bands.append((offset, band))
        offset += band
    return bands


def encode_stripes(raw: np.ndarray, bayer_order: str, frame_seq: int,
                   stripes: int = 2,
                   display: tuple[int, int] = (1920, 1080),
                   flags: int = 0, source_id: int = 0) -> list[np.ndarray]:
    """One camera frame -> one container per link.

    Each container is an independently valid bayerlink stream -- decodable
    alone into its band -- whose header says which slice it carries; a
    receiver pairs them by (source_id, frame_seq) and reassembles with
    :func:`reassemble`. The two scanouts share no vsync, so pairing is by
    header contents, never by capture timing.
    """
    raw = np.asarray(raw)
    if raw.ndim != 2:
        raise ValueError(f"raw frame must be (lines, samples), got {raw.shape}")
    full = raw.shape[0]
    return [
        encode_frame(raw[offset:offset + band], bayer_order, frame_seq,
                     display=display, flags=flags, source_id=source_id,
                     stripe=(index, stripes, offset, full))
        for index, (offset, band) in enumerate(split_stripes(full, stripes))
    ]


def reassemble(parts) -> tuple[Header, np.ndarray]:
    """Decoded stripes -> the whole frame, or a refusal naming the gap.

    ``parts`` is ``[(Header, band), ...]`` in any order, as
    :func:`decode_frame` produced them. Every stripe of the SAME frame must
    be present exactly once: bands must tile [0, full_height) with no gap
    and no overlap, and every header must agree on what frame this is. An
    incomplete set is refused -- the caller drops the whole frame, because
    a torn pair is worse than a dropped one.
    """
    parts = list(parts)
    if not parts:
        raise ValueError("no stripes to reassemble")
    first = parts[0][0]
    identity = ("fourcc", "width", "full_height", "frame_seq", "flags",
                "source_id", "stripe_count", "version")
    for header, _ in parts[1:]:
        for field in identity:
            if getattr(header, field) != getattr(first, field):
                raise ValueError(
                    f"stripes disagree on {field}: "
                    f"{getattr(first, field)!r} vs {getattr(header, field)!r} "
                    "-- these are not slices of one frame")
    if len(parts) != first.stripe_count:
        raise ValueError(
            f"frame {first.frame_seq} has {first.stripe_count} stripe(s); "
            f"got {len(parts)} -- refusing to assemble a torn frame")
    parts.sort(key=lambda part: part[0].stripe_offset)
    expected_offset = 0
    for header, band in parts:
        if header.stripe_offset != expected_offset:
            raise ValueError(
                f"stripe {header.stripe_index} starts at line "
                f"{header.stripe_offset}, expected {expected_offset}: the "
                "bands do not tile the frame")
        if band.shape[0] != header.height:
            raise ValueError(
                f"stripe {header.stripe_index} carries {band.shape[0]} "
                f"lines but its header claims {header.height}")
        expected_offset += header.height
    if expected_offset != first.full_height:
        raise ValueError(
            f"bands cover {expected_offset} of {first.full_height} lines")
    whole = Header(fourcc=first.fourcc, width=first.width,
                   height=first.full_height, frame_seq=first.frame_seq,
                   flags=first.flags, source_id=first.source_id)
    return whole, np.vstack([band for _, band in parts])


def detect_lane_map(frame: np.ndarray):
    """Which byte permutation makes this captured frame a bayerlink container.

    The wire protocol is defined over the memory byte sequence; which byte
    rides which video lane is a per-platform permutation. Rather than
    resolving it with a scope, feed any captured frame here: all six
    permutations are tried against the header's magic and CRC -- 32 bytes of
    evidence, so a false positive is not a realistic concern.

    Returns ``(permutation, Header)`` where ``permutation[k]`` says which
    captured channel holds container byte k -- directly usable as the
    ``lane_map`` of a receiver. Raises if none fits, with the diagnosis in
    the usual order of likelihood.
    """
    import itertools

    frame = np.asarray(frame, dtype=np.uint8)
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError(f"expected (height, width, 3), got {frame.shape}")
    for permutation in itertools.permutations(range(3)):
        candidate = frame[:, :, list(permutation)]
        try:
            header = Header.unpack(
                candidate.reshape(frame.shape[0], -1)[0, :HEADER_BYTES].tobytes())
        except ValueError:
            continue
        return tuple(permutation), header
    raise ValueError(
        "no byte permutation yields a valid header: the capture is not a "
        "bayerlink frame, or the link altered pixel VALUES (range clamp, "
        "YCbCr conversion, scaling) rather than merely permuting lanes.")
