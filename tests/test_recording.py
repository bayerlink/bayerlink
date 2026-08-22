# Copyright 2026 Serge Rabyking
# SPDX-License-Identifier: Apache-2.0
"""The recording format: the wire, kept -- header row and all."""
from __future__ import annotations

import numpy as np
import pytest

from bayerlink import encode_frame, recording


def container(seq: int = 3, order: str = "RGGB"):
    raw = np.random.default_rng(seq).integers(0, 4095, size=(64, 96),
                                              dtype=np.uint16)
    return encode_frame(raw, order, seq)


def test_a_recording_round_trips_through_the_file(tmp_path):
    path = tmp_path / "clip.npy"
    assert recording.save(path, [container(1), container(2)]) == 2
    pairs = list(recording.frames(path))
    assert [h.frame_seq for h, _ in pairs] == [1, 2]
    assert all(p.shape == (64, 96, 3) for _, p in pairs)


def test_a_single_container_is_a_stack_of_one(tmp_path):
    """Callers must never branch on whether a file holds one frame."""
    path = tmp_path / "still.npy"
    recording.save(path, container(5))
    assert recording.load(path).shape[0] == 1
    header, payload = next(recording.frames(path))
    assert header.frame_seq == 5 and payload.shape == (64, 96, 3)


def test_the_payload_survives_the_round_trip_exactly(tmp_path):
    """A recording is a conformance vector, so the bytes must be the
    bytes -- not merely an image that looks similar."""
    c = container(9)
    path = tmp_path / "exact.npy"
    recording.save(path, c)
    _, payload = next(recording.frames(path))
    assert np.array_equal(payload, np.asarray(c)[1:])


def test_a_header_that_disagrees_with_its_array_is_refused():
    """The failure this format exists to prevent: a file whose stated
    geometry is not the geometry it carries."""
    c = np.asarray(container(4))
    with pytest.raises(ValueError, match="payload lines"):
        recording.split(c[:-1])            # one row short of its own claim


def test_a_file_without_a_header_row_is_refused(tmp_path):
    """Payload saved on its own is not a recording; it is a picture
    whose mosaic order nobody can recover."""
    path = tmp_path / "bare.npy"
    np.save(path, np.zeros((64, 96, 3), np.uint8))
    with pytest.raises(ValueError):
        list(recording.frames(path))


def test_save_refuses_before_it_writes(tmp_path):
    path = tmp_path / "never.npy"
    with pytest.raises(ValueError):
        recording.save(path, np.zeros((10, 96, 3), np.uint8))
    assert not path.exists(), "a rejected recording still reached the disk"
