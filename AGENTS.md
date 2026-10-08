# AGENTS.md

GenClip mengubah video YouTube menjadi prompt optimal untuk LLM eksternal.

Alur:
YouTube URL
→ Transcript + audio
→ Story moments
→ Candidate 30–90 detik
→ Prompt
→ Output.

Prinsip:
- GitHub adalah source of truth.
- GenClip adalah preparation/prompt compiler, bukan penilai akhir.
- Local processing mengutamakan fakta, struktur, evidence, dan recall; jangan membuang kandidat berdasarkan taste.
- Transcript dan audio harus berada pada timeline yang konsisten.
- Audio adalah evidence internal GenClip, bukan input mentah yang dikirim ke LLM.
- External LLM menerima PROMPT SAJA. GenClip tidak mengirim raw audio, audio file, PCM/audio samples, audio stream, atau internal audio_path kepada external LLM.
- Audio dianalisis secara internal setelah candidate discovery; hasilnya menjadi AUDIO_EVIDENCE (misalnya RMS, peak, speech ratio, silence ratio, dan pause count) yang boleh dimasukkan ke prompt sebagai evidence.
- AUDIO_EVIDENCE memperkuat evaluasi candidate tetapi tidak boleh menjadi hard filter yang membuang candidate valid.
- Jangan menggambarkan arsitektur sebagai "mengirim audio ke LLM" atau "memberikan candidate audio kepada LLM". Deskripsi yang benar: GenClip menganalisis audio secara internal dan meneruskan hasil analisisnya sebagai evidence di dalam prompt; external LLM menerima prompt saja.
- Jangan mengklaim identitas speaker tanpa diarization yang nyata.
- Candidate harus mempertahankan evidence yang mendasari pembentukannya.
- 30–90 detik adalah hard gate, bukan target durasi.
- Tidak ada arbitrary candidate-count cap.
- START/END tidak boleh memotong kalimat, pemikiran, atau payoff.
- Prompt harus memisahkan FACTS/EVIDENCE dari interpretation atau hypothesis.
- Perubahan lintas file harus menjaga seluruh call chain dan data contract tetap konsisten.
- Jangan melakukan refactor yang tidak diperlukan.

Workflow:
pahami → telusuri → ubah → test → periksa diff → commit/push.

Aturan:
- Jangan mengklaim test yang tidak dilakukan.
- Jangan force push.
- Jangan menjalankan proses eksternal yang tidak diperlukan untuk perubahan.
- Setelah perubahan lolos test, commit dan push sebagai checkpoint GitHub.
