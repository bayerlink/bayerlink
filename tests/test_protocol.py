"""bayerlink v2 against its own spec: round trips, refusals, striping, the rate rule."""
import struct
import zlib

import numpy as np
import pytest

from bayerlink import pattern, protocol
from bayerlink.protocol import Header


# --------------------------------------------------------------------------- #
# 12P packing
# --------------------------------------------------------------------------- #

def test_pack12p_matches_the_spec_byte_for_byte():
    """The layout in PROTOCOL.md, checked against hand-computed bytes."""
    samples = np.array([0xABC, 0x123], dtype=np.uint16)
    packed = protocol.pack12p(samples)
    #   byte0 = P0[11:4] = 0xAB;  byte1 = P1[11:4] = 0x12
    #   byte2 = P1[3:0]<<4 | P0[3:0] = 0x3C
    assert packed.tolist() == [0xAB, 0x12, 0x3C]


@pytest.mark.parametrize("width,height", [(2, 1), (2028, 4), (16, 16)])
def test_pack12p_round_trips(width, height, rng=np.random.default_rng(20260808)):
    frame = rng.integers(0, 0x1000, (height, width)).astype(np.uint16)
    assert np.array_equal(protocol.unpack12p(protocol.pack12p(frame)), frame)


def test_pack12p_refuses_odd_width_and_wide_samples():
    with pytest.raises(ValueError, match="even"):
        protocol.pack12p(np.zeros((4, 3), np.uint16))
    with pytest.raises(ValueError, match="4095"):
        protocol.pack12p(np.array([0x1000, 0], np.uint16))


# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #

def test_header_round_trips_with_crc():
    header = Header(fourcc="pRCC", width=2028, height=540,
                    frame_seq=42, flags=protocol.FLAG_TEST_PATTERN,
                    source_id=3, stripe_index=1, stripe_count=2,
                    stripe_offset=538, full_height=1078)
    again = Header.unpack(header.pack())
    assert again == header
    assert again.bayer_order == "RGGB"
    assert again.bayer_phase == 0b00
    assert again.is_test_pattern
    assert len(header.pack()) == protocol.HEADER_BYTES == 48


def test_an_unstriped_header_normalises_and_pins_its_invariants():
    plain = Header(fourcc="pgCC", width=4, height=6, frame_seq=1)
    assert (plain.stripe_count, plain.stripe_offset,
            plain.full_height) == (1, 0, 6)
    with pytest.raises(ValueError, match="unstriped"):
        Header(fourcc="pgCC", width=4, height=6, frame_seq=1,
               stripe_offset=2)


def test_stripe_boundaries_must_preserve_the_cfa_phase():
    """An odd band boundary flips the Bayer phase mid-frame -- refused at
    construction, so no encoder can emit it and no vector can contain it."""
    with pytest.raises(ValueError, match="CFA"):
        Header(fourcc="pRCC", width=4, height=4, frame_seq=0,
               stripe_index=1, stripe_count=2, stripe_offset=3,
               full_height=8)
    with pytest.raises(ValueError, match="exceeds"):
        Header(fourcc="pRCC", width=4, height=6, frame_seq=0,
               stripe_index=1, stripe_count=2, stripe_offset=4,
               full_height=8)
    with pytest.raises(ValueError, match="stripe_index"):
        Header(fourcc="pRCC", width=4, height=2, frame_seq=0,
               stripe_index=2, stripe_count=2, stripe_offset=0,
               full_height=4)


def test_reserved_space_and_unknown_flags_are_refused():
    """MBZ means refused, not ignored: a future dialect must fail loudly."""
    good = bytearray(Header(fourcc="pRCC", width=4, height=2,
                            frame_seq=0).pack())
    for offset in (31, 40):
        poked = bytearray(good)
        poked[offset] = 1
        body = bytes(poked[:44])
        poked[44:48] = struct.pack("<I", zlib.crc32(body))
        with pytest.raises(ValueError, match="reserved"):
            Header.unpack(bytes(poked))
    flagged = bytearray(good)
    flagged[24 + 1] = 0x80                       # an undefined flag bit
    body = bytes(flagged[:44])
    flagged[44:48] = struct.pack("<I", zlib.crc32(body))
    with pytest.raises(ValueError, match="unknown flag"):
        Header.unpack(bytes(flagged))


def test_a_corrupted_header_is_refused_not_guessed():
    good = bytearray(Header(fourcc="pBCC", width=4, height=2,
                            frame_seq=0).pack())
    flipped = bytearray(good)
    flipped[12] ^= 0x01                          # width, inside the CRC
    with pytest.raises(ValueError, match="CRC"):
        Header.unpack(bytes(flipped))
    wrong_magic = bytearray(good)
    wrong_magic[0] ^= 0xFF
    with pytest.raises(ValueError, match="magic"):
        Header.unpack(bytes(wrong_magic))


def test_an_unknown_version_or_fourcc_is_refused():
    # A HISTORICAL v1 header (32 bytes, CRC at 28): refused by VERSION, with
    # the version named -- checked before the CRC, whose position moved, so
    # the diagnosis is "old version" and never "corrupt".
    v1_body = struct.pack("<IHHIIIII", protocol.MAGIC, 1, 32,
                          protocol.fourcc_code("pRCC"), 4, 2, 0, 0)
    v1 = v1_body + struct.pack("<I", zlib.crc32(v1_body)) + b"\x00" * 16
    with pytest.raises(ValueError, match="version 1.*historical"):
        Header.unpack(v1)
    # A future version is refused the same way.
    body = struct.pack(protocol._HEADER_FMT, protocol.MAGIC, 3, 48,
                       protocol.fourcc_code("pRCC"), 4, 2, 0, 0,
                       0, 0, 1, 0, 0, 2, 0)
    with pytest.raises(ValueError, match="version 3"):
        Header.unpack(body + struct.pack("<I", zlib.crc32(body)))
    body = struct.pack(protocol._HEADER_FMT, protocol.MAGIC, 2, 48,
                       protocol.fourcc_code("BA10"), 4, 2, 0, 0,
                       0, 0, 1, 0, 0, 2, 0)
    with pytest.raises(ValueError, match="not implemented"):
        Header.unpack(body + struct.pack("<I", zlib.crc32(body)))


def test_every_bayer_order_maps_to_its_phase_bits():
    for order, phase in {"RGGB": 0b00, "GRBG": 0b01,
                         "GBRG": 0b10, "BGGR": 0b11}.items():
        header = Header(fourcc=protocol.fourcc_for(order), width=4, height=2,
                        frame_seq=0)
        assert header.bayer_phase == phase, order


# --------------------------------------------------------------------------- #
# The frame container
# --------------------------------------------------------------------------- #

def test_encode_decode_round_trips_at_reference_geometry():
    """The reference setup: HQ camera at 2028x1078 inside 1080p.

    1078, not 1080: the header line costs one display line, so an N-line
    display carries at most N-1 camera lines — the first bug this suite
    caught, pinned by the refusal test below.
    """
    raw = pattern.generate("corners", 2028, 1078)
    frame = protocol.encode_frame(raw, "RGGB", frame_seq=7)
    assert frame.shape == (1080, 1920, 3) and frame.dtype == np.uint8

    header, decoded = protocol.decode_frame(frame)
    assert np.array_equal(decoded, raw)
    assert (header.width, header.height, header.frame_seq) == (2028, 1078, 7)

    # Padding really is padding: beyond the payload bytes, zeros only.
    lines = frame.reshape(1080, 1920 * 3)
    assert not lines[1:, header.line_bytes:].any()
    assert not lines[0, protocol.HEADER_BYTES:].any()


def test_a_full_height_frame_is_refused_the_header_line_is_not_free():
    with pytest.raises(ValueError, match="header line"):
        protocol.encode_frame(np.zeros((1080, 2028), np.uint16), "RGGB",
                              frame_seq=0)


def test_geometry_that_does_not_fit_is_refused_before_encoding():
    with pytest.raises(ValueError, match="display line carries"):
        protocol.check_geometry(3842, 100, (1920, 1080))
    with pytest.raises(ValueError, match="header line"):
        protocol.check_geometry(2028, 1080, (1920, 1080 - 1))


def test_the_rate_rule_matches_the_worked_examples():
    """PROTOCOL.md's examples, held as assertions: 1080p fits, 720p does not."""
    assert protocol.fits_line_rate(2028, total_line_slots=2200)      # 1080p
    assert not protocol.fits_line_rate(2028, total_line_slots=1650)  # 720p


def test_every_pattern_survives_the_full_container_round_trip():
    for name in pattern.PATTERNS:
        raw = pattern.generate(name, 64, 32)
        header, decoded = protocol.decode_frame(
            protocol.encode_frame(raw, "BGGR", frame_seq=1,
                                  display=(64, 40),
                                  flags=protocol.FLAG_TEST_PATTERN))
        assert np.array_equal(decoded, raw), name
        assert header.is_test_pattern


def test_patterns_hit_the_values_a_bad_link_clamps():
    """checker and corners must contain 0 and 4095 -- the limited-range
    casualties -- or the phase-0 loopback cannot catch a clamped link."""
    for name in ("checker", "corners"):
        raw = pattern.generate(name, 64, 32)
        assert raw.min() == 0 and raw.max() == 0xFFF, name


# --------------------------------------------------------------------------- #
# The committed vectors: the bytes other implementations conform against
# --------------------------------------------------------------------------- #

def test_the_committed_vectors_are_what_this_implementation_produces():
    """A drifted vector is a protocol change wearing a bugfix's clothes.

    This is the guard both ways: if protocol.py changes behaviour, this fails
    against the committed bytes; if someone regenerates the vectors to make it
    pass, the diff on the .bin files is visible in review.
    """
    import pathlib

    from bayerlink.protocol import FLAG_TEST_PATTERN

    vectors = pathlib.Path(__file__).parent.parent / "vectors"
    spec = {"corners_16x4_rggb.bin": ("corners", 16, 4, "RGGB", 3),
            "counting_16x8_bggr.bin": ("counting", 16, 8, "BGGR", 0)}
    stripes = ["counting_16x8_bggr_stripe0of2.bin",
               "counting_16x8_bggr_stripe1of2.bin"]
    for name, (mode, width, height, order, seq) in spec.items():
        committed = (vectors / name).read_bytes()
        frame = protocol.encode_frame(
            pattern.generate(mode, width, height), order, frame_seq=seq,
            display=(width, height + 4), flags=FLAG_TEST_PATTERN)
        assert frame.tobytes() == committed, name
        header, raw = protocol.decode_frame(
            np.frombuffer(committed, np.uint8).reshape(height + 4, width, 3))
        assert np.array_equal(raw, pattern.generate(mode, width, height)), name
        assert header.frame_seq == seq and header.bayer_order == order

    # The stripe pair is the counting frame split for two links: committed
    # bytes match the encoder, and reassembling the decoded pair reproduces
    # the WHOLE frame's payload -- the tiling rules pinned in vector form.
    whole = pattern.generate("counting", 16, 8)
    produced = protocol.encode_stripes(whole, "BGGR", frame_seq=0, stripes=2,
                                       display=(16, 8),
                                       flags=FLAG_TEST_PATTERN)
    parts = []
    for name, container in zip(stripes, produced):
        committed = (vectors / name).read_bytes()
        assert container.tobytes() == committed, name
        parts.append(protocol.decode_frame(
            np.frombuffer(committed, np.uint8).reshape(8, 16, 3)))
    header, raw = protocol.reassemble(parts)
    assert np.array_equal(raw, whole)
    assert header.stripe_count == 1 and header.height == 8


# --------------------------------------------------------------------------- #
# Lane detection and the luma tunnel: the bench helpers
# --------------------------------------------------------------------------- #

def test_detect_lane_map_recovers_any_permutation():
    from itertools import permutations

    raw = pattern.generate("gradient", 16, 4)
    container = protocol.encode_frame(raw, "GBRG", frame_seq=9,
                                      display=(16, 8))
    for perm in permutations(range(3)):
        # A link that put container byte k on channel perm[k]:
        scrambled = np.empty_like(container)
        for k in range(3):
            scrambled[:, :, perm[k]] = container[:, :, k]
        found, header = protocol.detect_lane_map(scrambled)
        assert found == perm
        assert header.frame_seq == 9 and header.bayer_order == "GBRG"


def test_detect_lane_map_refuses_a_value_mangling_link():
    raw = pattern.generate("gradient", 16, 4)
    container = protocol.encode_frame(raw, "RGGB", frame_seq=0,
                                      display=(16, 8))
    clamped = np.clip(container, 16, 235)        # a limited-range link
    with pytest.raises(ValueError, match="altered pixel VALUES"):
        protocol.detect_lane_map(clamped)


def _nasty_channel(grey, rng):
    """What a cheap dongle does to luma: range-squeeze, round, add noise."""
    y = grey[:, :, 0].astype(np.float64)
    y = 16.0 + y * (219.0 / 255.0)               # limited-range squeeze
    y = y + rng.normal(0.0, 1.0, y.shape)        # analog-ish noise
    return np.clip(np.round(y), 0, 255).astype(np.uint8)


def test_luma_tunnel_survives_a_nasty_channel_bit_exact():
    """The whole point: exact bytes through a lossy-looking path."""
    from bayerlink import tunnel

    rng = np.random.default_rng(20260808)
    phys = (192, 40)                              # inner width 32
    inner_w, _ = tunnel.inner_display(*phys)
    raw = pattern.generate("corners", inner_w * 2, 20)
    # ^ inner_w*2 samples = inner_w*3 bytes: exactly fills the inner line
    container = protocol.encode_frame(raw, "BGGR", frame_seq=3,
                                      display=(inner_w, 24))
    grey = tunnel.encode(container, phys)
    assert (grey[:, :, 0] == grey[:, :, 1]).all() and \
           (grey[:, :, 0] == grey[:, :, 2]).all()

    luma = _nasty_channel(grey, rng)
    recovered = tunnel.decode(luma, inner_height=container.shape[0])
    assert np.array_equal(recovered, container)

    header, decoded = protocol.decode_frame(recovered)
    assert np.array_equal(decoded, raw)
    assert header.frame_seq == 3 and header.bayer_order == "BGGR"


def test_luma_tunnel_refuses_a_channel_it_cannot_classify():
    from bayerlink import tunnel

    phys = (192, 40)
    inner_w, _ = tunnel.inner_display(*phys)
    raw = pattern.generate("gradient", inner_w * 2 - 2, 8)
    container = protocol.encode_frame(raw, "RGGB", frame_seq=0,
                                      display=(inner_w, 12))
    grey = tunnel.encode(container, phys)

    crushed = (grey[:, :, 0] // 16).astype(np.uint8)   # 4 counts per level
    with pytest.raises(ValueError, match="too noisy or too compressed"):
        tunnel.decode(crushed, inner_height=container.shape[0])

    with pytest.raises(ValueError, match="not a monotonic map"):
        tunnel.decode(255 - grey[:, :, 0], inner_height=container.shape[0])


# --------------------------------------------------------------------------- #
# Striping across links
# --------------------------------------------------------------------------- #

def test_split_stripes_tiles_evenly_or_refuses():
    assert protocol.split_stripes(10, 3) == [(0, 4), (4, 4), (8, 2)]
    assert protocol.split_stripes(8, 2) == [(0, 4), (4, 4)]
    assert protocol.split_stripes(6, 1) == [(0, 6)]
    with pytest.raises(ValueError, match="even"):
        protocol.split_stripes(9, 2)
    with pytest.raises(ValueError, match="even"):
        protocol.split_stripes(4, 3)


def test_striped_frame_reassembles_in_any_arrival_order():
    raw = pattern.generate("counting", 16, 10)
    parts = [protocol.decode_frame(container) for container in
             protocol.encode_stripes(raw, "GBRG", frame_seq=7, stripes=3,
                                     display=(16, 8), source_id=2)]
    for header, _ in parts:
        assert header.source_id == 2 and header.stripe_count == 3
    header, out = protocol.reassemble(reversed(parts))
    assert np.array_equal(out, raw)
    assert (header.height, header.frame_seq, header.source_id) == (10, 7, 2)


def test_a_torn_frame_is_refused_not_assembled():
    """One link dropped a frame: the set is incomplete, and assembling the
    survivors would hand downstream a plausible-looking wrong image."""
    raw = pattern.generate("checker", 16, 8)
    parts = [protocol.decode_frame(container) for container in
             protocol.encode_stripes(raw, "RGGB", frame_seq=1, stripes=2,
                                     display=(16, 8))]
    with pytest.raises(ValueError, match="torn"):
        protocol.reassemble(parts[:1])


def test_stripes_of_different_frames_or_cameras_never_mix():
    raw = pattern.generate("checker", 16, 8)
    def stripes(seq, source):
        return [protocol.decode_frame(c) for c in
                protocol.encode_stripes(raw, "RGGB", frame_seq=seq,
                                        stripes=2, display=(16, 8),
                                        source_id=source)]
    with pytest.raises(ValueError, match="frame_seq"):
        protocol.reassemble([stripes(1, 0)[0], stripes(2, 0)[1]])
    with pytest.raises(ValueError, match="source_id"):
        protocol.reassemble([stripes(5, 0)[0], stripes(5, 1)[1]])


# --------------------------------------------------------------------------- #
# The luma tunnel learns its channel
# --------------------------------------------------------------------------- #

def test_tunnel_survives_a_delayed_channel_bit_exactly():
    """Real capture sticks delay the line by a few pixels; the pilot must
    learn the delay along with the levels -- this was found on hardware,
    on the first frame the first stick ever returned."""
    from bayerlink import tunnel

    inner = tunnel.inner_display(1920, 1080)
    raw = pattern.generate("counting", 512, 240)
    container = protocol.encode_frame(raw, "RGGB", frame_seq=3, display=inner)
    luma = tunnel.encode(container, (1920, 1080))[:, :, 0]
    for delay in (0, 2, 7):
        shifted = np.zeros_like(luma)
        shifted[:, delay:] = luma[:, :1920 - delay]
        header, decoded = protocol.decode_frame(
            tunnel.decode(shifted, inner_height=inner[1]))
        assert np.array_equal(decoded, raw), f"delay {delay}"
        assert header.frame_seq == 3


def test_tunnel_refuses_a_channel_that_is_not_a_staircase():
    from bayerlink import tunnel

    flat = np.full((1080, 1920), 128, np.uint8)
    with pytest.raises(ValueError, match="not strictly increasing"):
        tunnel.decode(flat, inner_height=1079)
