# Copyright 2026 Serge Rabyking
# SPDX-License-Identifier: Apache-2.0
"""Recorded frames on disk: the wire, kept.

A recording is a stack of whole CONTAINERS -- the header row and the
payload rows beneath it, exactly the pixels the link carried. Not the
payload with the header thrown away, because that row is where the
frame states its own geometry, its CFA phase and its depth. A file
without it is a picture whose colours nobody can be sure of, and the
mistake is silent: a wrong phase looks like a broken ISP, not like a
broken recording.

The format lives HERE, with the codec that defines the wire, because
the alternative is what happened first: a source repo, a receiver
toolbox and an instrument each holding their own idea of what a
recording is, disagreeing about whether the header row is even part of
it.

    from bayerlink import recording
    for header, payload in recording.frames("grab.npy"):
        print(header.width, header.height, header.fourcc)

On disk it is one ``.npy`` holding a 4-D uint8 array,
``(frames, lines, samples, 3)`` with ``lines == height + 1``. NumPy
carries as many frames as fit in one array, so a clip is a stack and a
still is a stack of one -- there is no second shape to special-case.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .protocol import HEADER_BYTES, Header


def split(container: np.ndarray) -> tuple[Header, np.ndarray]:
    """One container into its header and its payload rows.

    Raises ValueError if the first row is not a header this library
    recognises, or if it disagrees with the array around it -- a
    recording that says one thing and measures another is refused here
    rather than at playback, where the symptom is a wrong picture.
    """
    container = np.asarray(container)
    if container.ndim != 3 or container.shape[-1] != 3:
        raise ValueError(
            f"a container is (lines, samples, 3); got {container.shape}")
    header = Header.unpack(
        np.ascontiguousarray(container[0]).tobytes()[:HEADER_BYTES])
    lines, width = container.shape[0], container.shape[1]
    if header.width != width:
        raise ValueError(
            f"the header says width {header.width}, the array is {width} "
            "samples wide")
    if header.height != lines - 1:
        raise ValueError(
            f"the header says height {header.height}, the array carries "
            f"{lines - 1} payload lines")
    return header, container[1:]


def load(path: str | Path, mmap: bool = True) -> np.ndarray:
    """Every container in a recording, as ``(frames, lines, samples, 3)``.

    A single container saved without a stack dimension is accepted and
    returned as a stack of one, so callers never branch on it.
    """
    stack = np.load(Path(path), mmap_mode="r" if mmap else None)
    if stack.ndim == 3:
        stack = stack[None]
    if stack.ndim != 4 or stack.shape[-1] != 3 or stack.dtype != np.uint8:
        raise ValueError(
            f"{Path(path).name}: a recording is a uint8 "
            "(frames, lines, samples, 3) array; got "
            f"{stack.shape} of {stack.dtype}")
    return stack


def frames(path: str | Path, mmap: bool = True):
    """Iterate a recording as ``(Header, payload)`` pairs."""
    for container in load(path, mmap=mmap):
        yield split(container)


def save(path: str | Path, containers) -> int:
    """Write containers to a recording, checking each one first.

    Every frame is split before anything is written, so a file that
    exists is a file that parses. Returns the number of frames.
    """
    stack = np.asarray(containers)
    if stack.ndim == 3:
        stack = stack[None]
    for container in stack:
        split(container)                 # refuses before it reaches disk
    np.save(Path(path), stack.astype(np.uint8, copy=False))
    return len(stack)
