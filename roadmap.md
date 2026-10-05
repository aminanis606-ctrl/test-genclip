# roadmap.md
ROADMAP_VERSION: 1.5
ROADMAP_UPDATED: 2026-10-05
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

## AUDIT & VALIDASI RUNTIME AUDIO PRODUCTION
- Pipeline audio internal meng-decode audio WebM/Opus (EBML container) secara in-memory menggunakan demuxer pure Python dan soundfile/miniaudio tanpa ketergantungan binary/C AV external.
- Menghasilkan bukti PCM nyata (RMS dB, Peak dB, speech ratio, silence ratio, pause count) yang membedakan sinyal audio secara presisi pada setiap candidate prefilter.
- Multi-tier decoder handling: WebM/Opus -> miniaudio (FLAC/MP3/WAV/Vorbis) -> soundfile -> wave fallback. Status terukur: `analyzed`, `decode_failed`, `missing_file`.
- Caching PCM terenkapsulasi (`_PCM_CACHE`) memastikan audio di-decode tepat 1 kali per file.
- Formatan `AUDIO_EVIDENCE` terhubung ke prompt compiler tanpa pernah membocorkan `audio_path` internal ke LLM eksternal.
- Catatan Keterbatasan CI: GitHub Actions runner (Ubuntu) memvalidasi penuh kompilasi APK (`gradle assembleDebug`) dan pengujian Python host unit/integration test. Namun, eksekusi JVM Android/Chaquopy secara live pada perangkat fisik/emulator tidak dapat dijalankan langsung di CI headless, sehingga pengujian end-to-end runtime Android divalidasi via APK build dan host Python test suite.

## STATUS
Selesai — Validasi pipeline audio production Chaquopy/Android dan integrasi evidence prefilter.
