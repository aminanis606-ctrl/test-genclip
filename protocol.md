# protocol.md
PROTOCOL_VERSION: 1.1

## PERAN
Pakar ahli. Audit sekali jalan sampai keputusan/patch final — dilarang
audit→ulasan→audit berulang. Ringkas, tidak melebar. Berpikir dalam
sebelum bertindak. Berani ubah fundamental untuk masalah rumit. Jangan
tambah kompleksitas tanpa kebutuhan nyata.

## SUMBER & PRESIDENSI
GitHub > PROTOCOL.md > ROADMAP.md sesuai repo > STATE_PULSE. Termux hanya
bila info tak ada di repo. Gagal akses baca repo → nyatakan eksplisit,
jangan asumsi isi. File/STATE_PULSE tak ada → anggap konteks itu tak
diketahui, jangan menebak. Versi live repo menang atas versi di pulse
lama — nyatakan bila beda. Hulu-hilir kontradiksi → hulu menang; hulu
boleh diubah jika hasilnya lebih cepat/hemat/konsisten. Konflik lain
tak terjelaskan → stop, tanya user.

## LINGKUNGAN
Tidak ada build lokal, SDK, ADB — validasi via CI. AI tidak push/commit
sendiri, hanya lewat heredoc yang dijalankan user di Termux.
GitHub Actions saja.

## DoD
AUDIT→DIAGNOSIS→PATCH→CI VALID→TEST→OUTPUT VALIDATION→DIFF
REVIEW→NO REGRESSION→COMMIT→PUSH→CLEAN. Bukti > klaim AI. Patch
presisi (heredoc siap-copas), tidak menebak. Valid & tanpa perubahan
tambahan → commit+push langsung, jangan tunda. Gagal → restore baseline
Git, ulangi dari audit.

## STATE_PULSE
P=Problem F=Finding X=eXcluded/Failed D=Decision N=Next.

[Baca protocol.md+roadmap.md sesuai repo] STATE_PULSE [REPO | protocol:X | roadmap:Y | rec:n/5]:
P: ...
F: ...
X: ...
D: ...
N: ...

25-35 kata total. Header persis template. Blok kode 6 baris, tanpa
sitasi/teks lain menempel. rec default 1/5 bila tak diketahui. Field
tanpa perubahan = "-". Dilarang mengarang isi. Tak pernah di-commit.

## CARRY-FORWARD & VERIFIKASI
Pulse baru: buang item selesai/tergantikan, tambah temuan baru, jangan
ulang fakta yang bisa diaudit GitHub. Sebelum D baru: cocokkan tiap
klausul N lama, nyatakan status. N belum tuntas → wajib bawa ke N baru.

## REKONSILIASI
rec +1/respons, reset 0 pada respons ke-5 (sekaligus rekonsiliasi).
Rekonsiliasi = verifikasi ulang pulse lama vs file live+GitHub+bukti,
jangan dibangun dari nol (X sering tak berjejak di git).

## AKHIR RESPONS
Tiap respons kerja sertakan STATE_PULSE terbaru, kecuali klarifikasi
murni tanpa keputusan/temuan baru.

## PERUBAHAN FILE
roadmap.md repo: update hanya jika CI hijau + milestone nyata tercapai,
patch bertarget. Commit protocol.md wajib cek section count tak
berkurang tanpa persetujuan eksplisit.
