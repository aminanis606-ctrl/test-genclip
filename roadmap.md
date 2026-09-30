# roadmap.md
ROADMAP_VERSION: 1.2
ROADMAP_UPDATED: 2026-09-29
REPO: test-genclip

## PIPELINE
URL VIDEO
→ transcript + timestamp
→ prefilter
→ prompt
→ AI validation/selection
→ yt-dlp download

## ATURAN
- Aplikasi mencari dan menyiapkan; AI memvalidasi dan memilih.
- Prefilter sederhana dan struktural.
- Kandidat 30–90 detik sebagai hard gate, bukan target.
- Story completeness > durasi.
- START/END harus aman; END = akhir pemikiran.
- `?` tidak otomatis menjadi END.
- Tidak ada candidate-count cap.
- Hindari kandidat hampir identik.
- Download final memakai `--force-keyframes-at-cuts`.

## STATUS
Aktif — penyelarasan prefilter dan prompt.
