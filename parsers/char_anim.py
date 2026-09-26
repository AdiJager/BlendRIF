# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Parsers for character skeleton (OBJCHIER tree) and animation
(OBANALLS).

Character RIFs (avp_huds/hnpc*.rif) store the skeleton as a recursive
tree of OBJCHIER containers inside the REBINFF2 payload. Each bone is
one OBJCHIER node holding:

    OBJHIERD   (4-byte parent_idx, always 0 in practice, + NUL-name)
    OBANALLS   (compact animation: all sequences for this bone)
    OBJCHIER*  (child bones, recursively nested)

Wrapper OBJCHIER nodes with no OBJHIERD of their own are transparent -
they just group children. The real hierarchy is encoded by nesting, not
by parent_idx; that field is a leftover from an older format and is
always zero in shipped RIFs.

The frame layout in OBANALLS is 36 bytes with no extra_data, unlike
OBASEQFR which appends an extra_data[] block. Do not confuse the two.

Note on find_all_chunks: do NOT use it for this structure. It both
drops real OBJHIERD chunks (nested too deep inside REBINFF2 for its
recursion cap) and picks up false OBJCHIER matches inside OBANALLS
payloads (each 36-byte frame carries a byte pattern that resembles a
chunk header). The recursive walker below avoids both problems by only
descending into OBJCHIER containers.

parse_obanalls validates num_sequences and num_frames against the
payload size before iterating. A corrupt chunk with a bogus count
(e.g. 0x7FFFFFFF) is rejected up front with a clear log message and
returns None, instead of relying on the reader raising once it walks
off the end.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from ..binary_reader import BinaryReader
from ..chunks import parse_chunks
from ..utils import log


# --- constants --------------------------------------------------------

# Object_Animation_Frame (animobs.hpp): 16 + 12 + 4 + 4 = 36 bytes.
FRAME_SIZE = 36

# HierarchyFrameFlag bitfield (animobs.hpp).
HIER_FLAG_DELTA_FRAME = 0x80000000
HIER_SOUND_INDEX_MASK = 0x7F000000
HIER_FLAG_MASK        = 0x00FFFFFF

# Sequence flags (OBASEQFL / SequenceFlag_* in animobs.hpp).
SEQ_FLAG_LOOPS            = 0x04
SEQ_FLAG_NO_LOOP          = 0x08
SEQ_FLAG_NO_INTERPOLATION = 0x10
SEQ_FLAG_HALF_FRAME_RATE  = 0x20

# Guard against pathological recursion on corrupt files.
_MAX_TREE_DEPTH = 64

# Sanity caps for OBANALLS. Real character RIFs are tiny (single
# digit sequences per bone, tens of frames per sequence). Anything
# above these limits cannot possibly be a valid payload.
_MAX_SEQUENCES           = 4096
_MAX_FRAMES_PER_SEQUENCE = 65536


# --- dataclasses ------------------------------------------------------

@dataclass
class CharBone:
    """One skeleton bone: name, parent name, and this bone's anim set."""
    name: str
    parent_name: str | None
    parent_idx: int = 0            # always 0 in shipped RIFs; kept for logs
    anim: "ObjAllSequences | None" = None


@dataclass
class AnimFrame:
    """One keyframe in OBANALLS (36 bytes on disk)."""
    orientation: tuple[float, float, float, float]  # x, y, z, w
    transform: tuple[int, int, int]                 # x, y, z
    at_frame_no: int                                # 0-65535
    flags: int

    def sound_index(self) -> int:
        """Extract the sound index (0-127) from flags."""
        return (self.flags & HIER_SOUND_INDEX_MASK) >> 24

    def is_delta(self) -> bool:
        """True if this is a delta (additive) frame."""
        return bool(self.flags & HIER_FLAG_DELTA_FRAME)


@dataclass
class AnimSequence:
    """One sequence inside an OBANALLS chunk."""
    num_frames: int
    sequence_number: int
    sub_sequence_number: int
    sequence_time: int  # ms
    frames: list[AnimFrame] = field(default_factory=list)

    def label(self) -> str:
        """Human-readable label like 'seq4_sub0' for logs/NLA tracks."""
        return f"seq{self.sequence_number}_sub{self.sub_sequence_number}"


@dataclass
class ObjAllSequences:
    """One OBANALLS chunk: all sequences + frames for one bone."""
    num_sequences: int
    sequences: list[AnimSequence] = field(default_factory=list)


# --- leaf parsers -----------------------------------------------------

def parse_objhierd(payload: bytes) -> tuple[int, str] | None:
    """Parse an OBJHIERD payload into (parent_idx, name), or None.

    Layout: int32 parent_idx, then a NUL-terminated ASCII name padded
    with zero bytes to a 4-byte boundary.
    """
    if len(payload) < 5:
        return None
    try:
        r = BinaryReader(payload)
        parent_idx = r.i32()
        name = r.strz()
        return parent_idx, name
    except (struct.error, IndexError) as e:
        log.warning(f"parse_objhierd: {type(e).__name__}: {e}")
        return None


def parse_obanalls(payload: bytes) -> ObjAllSequences | None:
    """Parse a compact OBANALLS payload into ObjAllSequences.

    Layout (animobs.cpp Object_Animation_All_Sequence_Chunk):
        int32 num_sequences
        per sequence:
            int32 num_frames
            int32 sequence_number
            int32 sub_sequence_number
            int32 sequence_time (ms)
            num_frames * 36 B (Object_Animation_Frame)

    Size-validates the header before iterating. Sequence headers are
    16 B; frames are FRAME_SIZE B. If the payload cannot hold the
    declared counts, the function returns None with a clear warning
    instead of iterating a bogus count until the reader runs dry.
    Reading is done with struct.unpack_from so byte positions stay
    explicit and bounds checks are straightforward.
    """
    if len(payload) < 4:
        return None
    try:
        num_sequences = struct.unpack_from("<i", payload, 0)[0]
        if num_sequences < 0 or num_sequences > _MAX_SEQUENCES:
            log.warning(f"parse_obanalls: implausible num_sequences="
                        f"{num_sequences} (payload {len(payload)} B)")
            return None
        # Minimum bytes: leading count (4) + one 16-byte header per
        # sequence. Frames add more per-sequence and are checked below.
        min_bytes = 4 + num_sequences * 16
        if min_bytes > len(payload):
            log.warning(f"parse_obanalls: payload {len(payload)} B too "
                        f"small for {num_sequences} sequence header(s) "
                        f"(need >= {min_bytes} B)")
            return None

        pos = 4
        sequences: list[AnimSequence] = []
        for _ in range(num_sequences):
            num_frames, seq_num, sub_num, seq_time = struct.unpack_from(
                "<iiii", payload, pos)
            pos += 16
            if num_frames < 0 or num_frames > _MAX_FRAMES_PER_SEQUENCE:
                log.warning(f"parse_obanalls: implausible num_frames="
                            f"{num_frames} in seq {seq_num}/{sub_num}")
                return None
            frames_bytes = num_frames * FRAME_SIZE
            if pos + frames_bytes > len(payload):
                log.warning(f"parse_obanalls: {num_frames} frame(s) need "
                            f"{frames_bytes} B, only "
                            f"{len(payload) - pos} B left "
                            f"(seq {seq_num}/{sub_num})")
                return None
            frames: list[AnimFrame] = []
            for _ in range(num_frames):
                orient = struct.unpack_from("<ffff", payload, pos)
                pos += 16
                xform = struct.unpack_from("<iii", payload, pos)
                pos += 12
                at_no = struct.unpack_from("<i", payload, pos)[0]
                pos += 4
                flags = struct.unpack_from("<i", payload, pos)[0]
                pos += 4
                frames.append(AnimFrame(
                    orientation=orient, transform=xform,
                    at_frame_no=at_no, flags=flags))
            sequences.append(AnimSequence(
                num_frames=num_frames,
                sequence_number=seq_num,
                sub_sequence_number=sub_num,
                sequence_time=seq_time,
                frames=frames))
        return ObjAllSequences(num_sequences=num_sequences,
                               sequences=sequences)
    except struct.error as e:
        log.warning(f"parse_obanalls: {e}")
        return None


# --- tree walker ------------------------------------------------------

def parse_objchier_tree(payload: bytes
                        ) -> tuple[list[CharBone], list[ObjAllSequences]]:
    """Walk an OBJCHIER tree; return (flat bones, flat anims).

    Bones are emitted in DFS pre-order (parent before child). Each bone
    is a node with an OBJHIERD leaf; wrapper nodes with no own OBJHIERD
    are transparent and pass their parent name down unchanged.

    The tree lives inside the REBINFF2 wrapper, so the caller should
    pass that wrapper's payload, not the raw decoded buffer.
    """
    flat_bones: list[CharBone] = []
    flat_anims: list[ObjAllSequences] = []

    def walk(data: bytes, parent_name: str | None, depth: int) -> None:
        if depth > _MAX_TREE_DEPTH:
            log.warning("parse_objchier_tree: depth cap hit")
            return
        chunks = parse_chunks(data, quiet=True, resync_max=64)
        if chunks is None:
            return

        own_name: str | None = None
        own_idx: int = 0
        own_anim: ObjAllSequences | None = None
        child_payloads: list[bytes] = []

        for cid, cdata in chunks:
            if cid == "OBJHIERD":
                parsed = parse_objhierd(cdata)
                if parsed is not None:
                    own_idx, own_name = parsed
            elif cid == "OBANALLS":
                a = parse_obanalls(cdata)
                if a is not None:
                    own_anim = a
            elif cid == "OBJCHIER":
                child_payloads.append(cdata)
            # All other chunk types (OBJHEAD1, SHAPES, RBOBJECT, ...) are
            # deliberately skipped - they belong to geometry, not skeleton.

        if own_name:
            flat_bones.append(CharBone(
                name=own_name,
                parent_name=parent_name,
                parent_idx=own_idx,
                anim=own_anim))
            if own_anim is not None:
                flat_anims.append(own_anim)
            next_parent = own_name
        else:
            next_parent = parent_name

        for cp in child_payloads:
            walk(cp, next_parent, depth + 1)

    walk(payload, None, 0)
    return flat_bones, flat_anims