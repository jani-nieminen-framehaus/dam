#!/usr/bin/env python3
"""Vocabulary frequency exploration for Phase 0 — read-only on dam.db.

Dumps three reports to /tmp/ for review:
  1. top 500 keywords by frequency
  2. all keywords with frequency >= 10
  3. keywords with frequency in 1..9 (the long tail)

Read-only. Does not modify dam.db.
"""
import sqlite3
from pathlib import Path

DB = "/Users/janinieminen/Documents/dam/dam.db"
OUT_DIR = Path("/tmp")

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

freqs = conn.execute(
    """
    SELECT k.keyword, COUNT(*) AS cnt
    FROM image_keywords ik
    JOIN keywords k ON ik.keyword_id = k.id
    GROUP BY k.keyword
    ORDER BY cnt DESC
    """
).fetchall()

with (OUT_DIR / "dam_vocab_top500.txt").open("w") as f:
    for r in freqs[:500]:
        f.write(f"{r['cnt']:>6}  {r['keyword']}\n")

ge10 = [r for r in freqs if r["cnt"] >= 10]
with (OUT_DIR / "dam_vocab_ge10.txt").open("w") as f:
    for r in ge10:
        f.write(f"{r['cnt']:>6}  {r['keyword']}\n")

tail = [r for r in freqs if r["cnt"] < 10]
with (OUT_DIR / "dam_vocab_tail.txt").open("w") as f:
    for r in tail[:200]:
        f.write(f"{r['cnt']:>6}  {r['keyword']}\n")

print(f"total distinct keywords:  {len(freqs)}")
print(f"  cnt >= 1000:            {sum(1 for r in freqs if r['cnt'] >= 1000)}")
print(f"  cnt >= 500:             {sum(1 for r in freqs if r['cnt'] >= 500)}")
print(f"  cnt >= 100:             {sum(1 for r in freqs if r['cnt'] >= 100)}")
print(f"  cnt >= 50:              {sum(1 for r in freqs if r['cnt'] >= 50)}")
print(f"  cnt >= 10:              {sum(1 for r in freqs if r['cnt'] >= 10)}")
print(f"  cnt 1..9 (long tail):   {len(tail)}")
conn.close()
