"""Standalone RIF chunk dumper for AvP (1999) RIF files.

Paste into Blender's Scripting workspace (New -> Paste -> Run Script /
Alt+P), edit the config block, read output in Window -> Toggle System
Console.

For each file:
  1. Decodes with the installed addon's load_rif_auto.
  2. Walks the chunk tree, tallying every chunk ID with count and
     shallowest depth.
  3. Prints the table sorted by ID.
  4. For chunk IDs listed in HEX_DUMP_IDS, dumps the first N
     occurrences of each as hex+ascii.

NOTE: parse_chunks() returns chunk IDs as *str* (decoded ASCII), not
bytes. HEX_DUMP_IDS is therefore a list of str. Passing bytes here
silently produced "NOT PRESENT" for chunks that were in fact present
in the table (bug in the first version of this tool).
"""

import os

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

AVP_ROOT = r"D:\Steam\steamapps\common\Aliens versus Predator Classic"

PATHS = [
    os.path.join(AVP_ROOT, r"avp_rifs\nostromo.rif"),
    os.path.join(AVP_ROOT, r"avp_rifs\Derelict.RIF"),
    # Uncomment to inspect character RIFs:
    # os.path.join(AVP_ROOT, r"avp_huds\hnpchugger.rif"),
    # os.path.join(AVP_ROOT, r"avp_huds\hnpcmarine.rif"),
]

# Chunk IDs whose payloads are hex-dumped. STR, not bytes.
HEX_DUMP_IDS = [
    "OBJTRAK2",
    "VIOBJECT",
    "VOBJPROP",
    "MODULEDT",
    "ADJMDLEP",
    "VMDARRAY",
]

# How many occurrences of each target ID to dump (0 = all).
HEX_DUMP_LIMIT_PER_ID = 3

# Max bytes dumped per occurrence.
HEX_BYTES = 256

# Recursion limits.
MAX_DEPTH = 16
RESYNC_MAX = 64


# ---------------------------------------------------------------------------
# Code below - no need to edit
# ---------------------------------------------------------------------------

def _hex_dump(data, limit=HEX_BYTES):
    """Print a compact hex+ascii dump of `data` up to `limit` bytes."""
    chunk = data[:limit]
    truncated = len(data) > limit
    for off in range(0, len(chunk), 16):
        row = chunk[off:off + 16]
        hex_part = " ".join(f"{b:02x}" for b in row)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        print(f"      {off:04x}  {hex_part:<48}  |{ascii_part}|")
    if truncated:
        print(f"      ... ({len(data) - limit} more bytes)")


def _walk(data, seen, payloads_by_id, depth, max_depth, resync_max,
          parse_chunks, collect_ids):
    """Recursively walk a decoded RIF, tallying chunk IDs.

    seen: {chunk_id(str): [count, min_depth]}
    payloads_by_id: {chunk_id(str): [payload, ...]} - all occurrences
                    for chunk IDs in collect_ids
    """
    if depth > max_depth:
        return
    chunks = parse_chunks(data, quiet=True, resync_max=resync_max)
    if chunks is None:
        return
    for cid, cdata in chunks:
        rec = seen.get(cid)
        if rec is None:
            seen[cid] = [1, depth]
        else:
            rec[0] += 1
            if depth < rec[1]:
                rec[1] = depth
        if cid in collect_ids:
            payloads_by_id.setdefault(cid, []).append(cdata)
        _walk(cdata, seen, payloads_by_id, depth + 1, max_depth,
              resync_max, parse_chunks, collect_ids)


def dump_one(path, max_depth=MAX_DEPTH, resync_max=RESYNC_MAX,
             hex_ids=HEX_DUMP_IDS, per_id_limit=HEX_DUMP_LIMIT_PER_ID,
             hex_bytes=HEX_BYTES):
    """Decode one RIF and print the full chunk ID table (+ hex dumps)."""
    from avp_rif_importer.chunks import parse_chunks
    from avp_rif_importer.rif_loader import load_rif_auto

    print()
    print("=" * 70)
    print(f"FILE: {path}")
    print("=" * 70)

    if not os.path.isfile(path):
        print(f"  !! file not found: {path}")
        return None

    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        print(f"  !! read error: {e}")
        return None
    print(f"  file size: {len(raw)} bytes")

    decoded = load_rif_auto(raw, verbose=False)
    if decoded is None:
        print("  !! decode failed")
        return None
    print(f"  decoded:   {len(decoded)} bytes")

    seen = {}
    payloads_by_id = {}
    collect_ids = set(hex_ids)
    _walk(decoded, seen, payloads_by_id, 0, max_depth, resync_max,
          parse_chunks, collect_ids)

    print()
    print(f"  {'ID':<14} {'count':>8} {'min_depth':>10}")
    print(f"  {'-' * 14} {'-' * 8} {'-' * 10}")
    for cid in sorted(seen.keys()):
        cnt, d = seen[cid]
        name = cid if isinstance(cid, str) else repr(cid)
        print(f"  {name:<14} {cnt:>8} {d:>10}")

    if hex_ids:
        print()
        print(f"  --- hex dumps (up to {per_id_limit or 'all'} "
              f"occurrence(s) per ID, {hex_bytes} bytes each) ---")
        for target in hex_ids:
            payloads = payloads_by_id.get(target)
            if not payloads:
                print(f"\n  {target}: NOT PRESENT")
                continue
            n = len(payloads)
            shown = n if per_id_limit <= 0 else min(n, per_id_limit)
            print(f"\n  {target}: {n} occurrence(s), "
                  f"showing {shown} (sizes: "
                  f"{', '.join(str(len(p)) for p in payloads[:8])}"
                  f"{' ...' if n > 8 else ''})")
            for i, payload in enumerate(payloads[:shown]):
                print(f"    --- occurrence {i} ({len(payload)} B) ---")
                _hex_dump(payload, limit=hex_bytes)

    return seen


if __name__ == "__main__":
    for p in PATHS:
        dump_one(p)