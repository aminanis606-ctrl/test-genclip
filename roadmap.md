# roadmap.md
ROADMAP_VERSION: 1.1
ROADMAP_UPDATED: 2026-09-28
REPO: test-genclip

## PIPELINE v1

M1 — Source
URL YouTube → SRT + timeline valid.

M2 — Story Discovery
Timeline → Story Units berdasarkan konteks cerita, bukan keyword.

M3 — Candidate Ranking
Story Units → kandidat clip + context + ranking + dedup.
M3 menyiapkan kandidat, bukan memilih final.

M4 — GenClip Protocol
Kandidat → prompt.txt.
AI memeriksa video dan memilih kandidat final.

## OUTPUT
SRT → Story Units → Candidates → prompt.txt → AI → GenClip

## STATUS
Aktif: M1 — Source

## RIWAYAT
- v1.1 (2026-09-28): pembagian tanggung jawab M1–M4 diperjelas.
- v1.0 (2026-09-28): protocol.md universal dipasang.
