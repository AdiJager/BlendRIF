"""Dump recursive OBJCHIER tree from a character RIF.

Descends into REBINFF2 first (that's where the whole tree lives), then
recurses ONLY into OBJCHIER containers. Leaf chunks (OBJHIERD,
OBANALLS, OBHIERNM) are read but their payloads are NOT scanned for
nested chunks - that's how find_all_chunks was picking up false
matches and dropping real ones.
"""

import os

RIF_PATH   = r"D:\Steam\steamapps\common\Aliens versus Predator Classic\avp_huds\hnpchugger.rif"
WRITE_FILE = True
OUT_PATH   = r"G:\RIF Importer\dump_char_tree.txt"

MAX_DEPTH          = 20
MAX_LEAVES_PER_NODE = 200   # cap per node, not global
SHOW_HIERD_PID     = True


def main():
    try:
        from avp_rif_importer.rif_loader import load_rif_auto
        from avp_rif_importer.chunks import parse_chunks
    except ImportError as e:
        print(f"ERROR: {e}")
        return

    with open(RIF_PATH, "rb") as f:
        raw = f.read()
    decoded = load_rif_auto(raw, verbose=False)
    if decoded is None:
        print("ERROR: decode failed")
        return

    out = []
    def emit(s=""):
        print(s)
        out.append(s)

    # Global counters
    counters = {"OBJCHIER": 0, "OBJHIERD": 0, "OBANALLS": 0, "OBHIERNM": 0}

    def walk(data, depth):
        """Recurse into OBJCHIER only; print/collect leaves."""
        if depth > MAX_DEPTH:
            emit(f"{'  ' * depth}<MAX_DEPTH>")
            return
        chunks = parse_chunks(data, quiet=True, resync_max=64)
        if chunks is None:
            emit(f"{'  ' * depth}<parse_chunks FAILED on "
                 f"{len(data)} B>")
            return

        # Print summary of this node
        n_ch = sum(1 for c, _ in chunks if c == "OBJCHIER")
        n_hd = sum(1 for c, _ in chunks if c == "OBJHIERD")
        n_al = sum(1 for c, _ in chunks if c == "OBANALLS")
        n_nm = sum(1 for c, _ in chunks if c == "OBHIERNM")
        n_other = len(chunks) - n_ch - n_hd - n_al - n_nm
        emit(f"{'  ' * depth}node: {len(chunks)} chunks  "
             f"[CHIER={n_ch} HIERD={n_hd} ANALLS={n_al} NM={n_nm} "
             f"other={n_other}]")

        shown = 0
        for cid, cdata in chunks:
            if cid == "OBJCHIER":
                counters["OBJCHIER"] += 1
                emit(f"{'  ' * depth}  OBJCHIER "
                     f"({len(cdata)} B) -> descend")
                walk(cdata, depth + 1)
            elif cid == "OBJHIERD":
                counters["OBJHIERD"] += 1
                if shown < MAX_LEAVES_PER_NODE:
                    pid = int.from_bytes(cdata[:4], "little", signed=True) \
                          if len(cdata) >= 4 else -999
                    name = cdata[4:].split(b"\x00")[0].decode(
                        "ascii", errors="replace")
                    emit(f"{'  ' * depth}  OBJHIERD pid={pid} name={name!r}")
                shown += 1
            elif cid == "OBANALLS":
                counters["OBANALLS"] += 1
                if shown < MAX_LEAVES_PER_NODE:
                    nseq = int.from_bytes(cdata[:4], "little", signed=True) \
                           if len(cdata) >= 4 else -1
                    emit(f"{'  ' * depth}  OBANALLS nseq={nseq} "
                         f"({len(cdata)} B)")
                shown += 1
            elif cid == "OBHIERNM":
                counters["OBHIERNM"] += 1
                name = cdata.split(b"\x00")[0].decode("ascii",
                                                      errors="replace")
                emit(f"{'  ' * depth}  OBHIERNM {name!r}")
            # else: silent - do NOT descend into non-hierarchy payloads

    # --- top level: descend into REBINFF2, skip other wrappers ---
    emit("=" * 72)
    emit(f"OBJCHIER TREE: {os.path.basename(RIF_PATH)}")
    emit(f"decoded: {len(decoded)} bytes")
    emit("=" * 72)

    top = parse_chunks(decoded, quiet=True, resync_max=64)
    if top is None:
        emit("ERROR: top-level parse failed")
        return
    emit("")
    emit(f"top level: {len(top)} chunks")
    for cid, cdata in top:
        emit(f"  {cid} ({len(cdata)} B)")

    emit("")
    emit("--- descending into REBINFF2 ---")
    for cid, cdata in top:
        if cid in ("REBINFF2", "REBCRIF1"):
            walk(cdata, 0)
        else:
            # Some RIFs have the tree at top level directly
            walk(cdata, 0)

    emit("")
    emit("=" * 72)
    emit("FINAL COUNTS:")
    for k, v in counters.items():
        emit(f"  {k:<10} {v}")
    emit("=" * 72)
    emit("")
    emit("Diagnostic reference: OBJCHIER=40 OBJHIERD=39 OBANALLS=39 "
         "OBHIERNM=1 (from prior scan)")

    if WRITE_FILE:
        try:
            with open(OUT_PATH, "w", encoding="utf-8") as f:
                f.write("\n".join(out))
            print(f"\nWritten to: {OUT_PATH}")
        except OSError as e:
            print(f"WARN: {e}")


if __name__ == "__main__":
    main()