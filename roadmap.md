# roadmap.md
ROADMAP_VERSION: 1.3
ROADMAP_UPDATED: 2026-09-29
REPO: test-genclip

## PIPELINE
URL VIDEO
→ transcript + timestamp
→ prefilter
→ prompt AI validation/selection + yt-dlp download

## ATURAN PREFILTER
- Prefilter membaca transcript dan timestamp secara langsung.
- Mencari momen cerita secara kronologis.
- START harus natural dan tidak memotong kalimat atau pikiran.
- END harus berhenti pada akhir pemikiran.
- Tanda `?` bukan otomatis END.
- Kandidat tidak boleh overlap.
- 30–90 detik adalah hard gate, bukan target durasi.
- Kelengkapan cerita lebih penting daripada durasi.
- Tidak ada batas jumlah kandidat.

## STATUS
Aktif — penyederhanaan dan penyempurnaan prefilter.
