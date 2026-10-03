# roadmap.md
ROADMAP_VERSION: 1.4
ROADMAP_UPDATED: 2026-10-02
REPO: test-genclip

## PIPELINE
URL VIDEO
→ transcript + timestamp + audio (analisis internal GenClip)
→ prefilter (recall-first discovery kandidat cerita 30–90s)
→ prompt compiler (fakta, evidence, timestamp, & instruksi evaluasi untuk LLM eksternal)
→ LLM eksternal memakai URL dan tool/kemampuannya sendiri untuk mendengarkan audio

## BATAS AUDIO
- Audio GenClip digunakan untuk analisis internal, bukan dikirim ke LLM eksternal.
- Jangan menganggap `audio_path` harus masuk ke prompt compiler.
- Audit harus memastikan audio benar-benar digunakan internal, bukan sekadar diunduh/divalidasi.


## ATURAN PREFILTER & PROMPT COMPILER
- Prefilter membaca transcript dan timestamp secara langsung.
- Mencari momen cerita secara kronologis lintas transkrip.
- Overlap kandidat dipertahankan pada tahap discovery (recall-first); pengelompokan (grouping) menangani transitive overlap.
- START harus natural dan tidak memotong kalimat atau pikiran.
- END harus berhenti pada akhir pemikiran.
- Tanda `?` bukan otomatis END.
- 30–90 detik adalah hard gate, bukan target durasi.
- Kelengkapan cerita lebih penting daripada durasi.
- Tidak ada arbitrary candidate-count cap.
- Prompt Compiler menyajikan fakta/evidence transkrip & timestamp terpisah dari instruksi evaluasi LLM.
- HANYA menghasilkan template command yt-dlp untuk LLM; tidak menjalankan yt-dlp lokal di pipeline GenClip.

## STATUS
Aktif — konsolidasi prefilter dan prompt compiler GenClip.
