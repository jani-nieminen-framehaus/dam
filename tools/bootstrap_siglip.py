#!/usr/bin/env python3
"""Phase 5: Bootstrap SigLIP embeddings + zero-shot classifier tags.

Single pass per image: encode once, write embedding, classify against vocab,
write tags with confidence. More efficient than two separate passes.

Resumable: SELECT only WHERE the relevant timestamp IS NULL. Re-running picks
up where it stopped. Per-batch commits keep progress durable.

Run:
  /opt/homebrew/bin/python3 /Users/janinieminen/Documents/dam/tools/bootstrap_siglip.py all
"""
import sys, os, time, argparse, sqlite3, json
from pathlib import Path

import sqlite_vec

sys.path.insert(0, "/Users/janinieminen/Documents/dam")
import dam_siglip

DB = Path(os.path.expanduser("~/.dam/dam.db"))
PREVIEW_DIR = Path("/Users/janinieminen/Documents/dam/previews")
THUMB_DIR = Path("/Users/janinieminen/Documents/dam/thumbs")

INFERENCE_BATCH = 32
OUTER_CHUNK = 256
CONFIDENCE_THRESHOLD = 0.10
MAX_TAGS_PER_IMAGE = 12

STATUS_FILE = Path(os.path.expanduser("~/.dam/bootstrap_siglip_status.json"))


def open_db():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def pick_input_path(image_id):
    for d in (PREVIEW_DIR, THUMB_DIR):
        p = d / f"{image_id}.jpg"
        if p.exists():
            return p
    return None


def write_status(stage, current, total, eta_min):
    try:
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATUS_FILE.write_text(json.dumps({
            "stage": stage, "current": current, "total": total,
            "eta_minutes": round(eta_min, 1), "timestamp": time.time(),
        }))
    except Exception:
        pass


def bootstrap(do_embed, do_classify):
    conn = open_db()

    if do_embed and do_classify:
        rows = conn.execute(
            "SELECT id FROM images "
            "WHERE siglip_embedded_at IS NULL OR classified_at IS NULL "
            "ORDER BY id"
        ).fetchall()
        stage = "embed+classify"
    elif do_embed:
        rows = conn.execute(
            "SELECT id FROM images WHERE siglip_embedded_at IS NULL ORDER BY id"
        ).fetchall()
        stage = "embed"
    else:
        rows = conn.execute(
            "SELECT id FROM images WHERE classified_at IS NULL "
            "AND siglip_embedded_at IS NOT NULL ORDER BY id"
        ).fetchall()
        stage = "classify"

    print(f"[{stage}] {len(rows)} images pending", flush=True)
    if not rows:
        conn.close()
        return

    work = []
    no_input = 0
    for r in rows:
        p = pick_input_path(r["id"])
        if p is None:
            no_input += 1
            continue
        work.append((r["id"], p))
    print(f"[{stage}] {len(work)} have input files; {no_input} lack preview/thumb (skipped)", flush=True)
    if not work:
        conn.close()
        return

    tags = None
    vocab_emb = None
    if do_classify:
        tags = dam_siglip.load_vocabulary()
        print(f"[{stage}] loading vocab ({len(tags)} tags)...", flush=True)
        vocab_emb = dam_siglip.precompute_vocab_embeddings(tags)

    dam_siglip.get_model()

    t0 = time.time()
    embedded = 0
    classified = 0
    failed = 0

    for chunk_start in range(0, len(work), OUTER_CHUNK):
        chunk = work[chunk_start : chunk_start + OUTER_CHUNK]
        paths = [r[1] for r in chunk]
        id_by_path = {r[1]: r[0] for r in chunk}

        try:
            results = dam_siglip.encode_images_with_paths(
                paths, batch_size=INFERENCE_BATCH
            )
        except Exception as e:
            print(f"[{stage}] BATCH ERROR at chunk {chunk_start}: {e}", flush=True)
            failed += len(chunk)
            continue

        for path, emb in results:
            img_id = id_by_path.get(path)
            if img_id is None:
                continue
            try:
                if do_embed:
                    dam_siglip.write_image_embedding(conn, img_id, emb)
                    embedded += 1
                if do_classify:
                    scored = dam_siglip.classify_image(
                        emb, vocab_emb, tags,
                        threshold=CONFIDENCE_THRESHOLD,
                        max_tags=MAX_TAGS_PER_IMAGE,
                    )
                    dam_siglip.write_classifier_tags(conn, img_id, scored)
                    classified += 1
            except Exception as e:
                print(f"[{stage}] DB write FAIL id={img_id}: {e}", flush=True)
                failed += 1

        failed_in_chunk = len(chunk) - len(results)
        if failed_in_chunk > 0:
            failed += failed_in_chunk

        conn.commit()

        processed = embedded if do_embed else classified
        elapsed = time.time() - t0
        rate = processed / elapsed if elapsed > 0 else 0
        eta = (len(work) - processed) / rate / 60 if rate > 0 else 0
        print(
            f"[{stage}] {processed}/{len(work)} ({100*processed/len(work):.1f}%) "
            f"| {rate:.1f} img/s | elapsed {elapsed/60:.1f}min | ETA {eta:.1f}min",
            flush=True,
        )
        write_status(stage, processed, len(work), eta)

    conn.commit()
    print(
        f"[{stage}] DONE: embedded={embedded} classified={classified} "
        f"failed={failed} no_input={no_input} elapsed={(time.time()-t0)/60:.1f}min",
        flush=True,
    )

    n_emb = conn.execute("SELECT COUNT(*) FROM image_embeddings_siglip").fetchone()[0]
    n_classified = conn.execute(
        "SELECT COUNT(*) FROM images WHERE classified_at IS NOT NULL"
    ).fetchone()[0]
    print(f"[{stage}] DB state: image_embeddings_siglip={n_emb}, classified_at NOT NULL={n_classified}", flush=True)
    write_status(stage + "_done", n_emb, len(rows), 0.0)
    conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", nargs="?", default="all",
                    choices=["all", "embed", "classify"])
    args = ap.parse_args()
    do_embed = args.mode in ("all", "embed")
    do_classify = args.mode in ("all", "classify")
    bootstrap(do_embed, do_classify)


if __name__ == "__main__":
    main()
