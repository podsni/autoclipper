# AutoClipper

Studio web berbahasa Indonesia untuk mengubah video YouTube berizin menjadi klip vertikal: tempel URL, pilih jumlah klip, transkripsi, render, tinjau, lalu unduh.

## Fitur

- Antrean satu worker dengan riwayat dan cache lokal.
- Transkripsi **Deepgram Nova-3** dengan timestamp kata; cache digunakan ulang agar potongan berikutnya tidak mengulang STT.
- Pemilihan kandidat **heuristik**, bukan jaminan viral atau verifikasi fakta.
- Output H.264/AAC **720×1280**, subtitle tertanam dan SRT/ASS terpisah.
- Subtitle Clean/Highlight; highlight hanya memakai timestamp kata nyata.
- Preset **Seperti contoh**: judul kuning, gambar utuh di tengah, background blur gelap, subtitle dan kredit sumber. Judul dapat diisi sendiri.
- Caption **Groq** (default `openai/gpt-oss-20b`), Gemini opsional, serta template lokal yang diberi label bukan AI. Hasil dapat diedit, disalin, dan diunduh sebagai TXT.
- Preview MP4, unduhan individual dan ZIP.

## Instalasi

Diperlukan Python 3.13+, [uv](https://docs.astral.sh/uv/), FFmpeg/FFprobe dengan libx264/AAC/libass, font DejaVu Sans, dan Node.js yang didukung yt-dlp untuk mengakses video YouTube. Linux/WSL adalah lingkungan yang diuji.

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env
chmod 600 .env
# Isi kredensial di .env menggunakan editor lokal.
.venv/bin/python app.py
```

Buka **http://127.0.0.1:8787**. Kode transcriber yang dibutuhkan sudah disertakan di `vendor/youtube-clipper/`; tidak memerlukan direktori developer atau clone kedua.

Kunci API dibaca hanya oleh server. Jangan masukkan kunci ke frontend, URL, Git, screenshot, atau chat grup. Gunakan environment proses atau `.env` checkout ini; parameter model opsional `GROQ_CAPTION_MODEL` dan `GEMINI_CAPTION_MODEL` dapat diberikan melalui environment proses, bukan input publik.

## Cara penggunaan

1. Tempel URL satu video YouTube yang berhak Anda gunakan.
2. Pilih 1–8 klip, bahasa audio, gaya subtitle dan preset video.
3. Isi judul atas bila perlu; jika kosong, digunakan cuplikan teks kandidat transkrip. Judul panjang dipadatkan menjadi maksimal dua baris.
4. Konfirmasikan hak penggunaan dan biaya transkripsi, lalu klik **Buat klip**.
5. Tinjau preview, konteks, ejaan, atribusi dan batas potongan. Unduh MP4, SRT, ASS atau ZIP.
6. Pada kartu klip, pilih Shorts/TikTok dan gaya caption. Klik provider yang diinginkan. Tombol Groq/Gemini mengirim transkrip klip ke provider; template lokal tidak memakai API.

Preset baru berlaku pada render baru; tidak mengubah video lama. Preset reference menjaga frame utuh sehingga mengabaikan mode crop. Draft caption yang diedit belum disimpan setelah refresh atau pergantian proyek.

## Biaya dan batasan

- Deepgram menerima **seluruh audio sumber**, bukan hanya detik klip. Maksimum durasi sumber satu jam; maksimum delapan klip per job.
- Sumber dan transkrip dicache menurut ID. Cache tetap memakai bahasa aslinya, bukan menerjemahkan ketika pilihan bahasa berubah.
- Caption AI dapat dikenai biaya/kuota provider. Tidak ada retry API berbayar atau fallback provider diam-diam.
- Model Gemini bisa timeout/503 meskipun daftar model dapat diakses. Model OpenCode gratis tidak diintegrasikan: akses API eksternal terhalang pembatasan free tier pada pengujian. Tidak ada fallback ke model OpenCode berbayar.
- Pemilihan heuristik bisa mengembalikan kurang dari jumlah permintaan ketika ucapan tidak cukup. Akurasi potongan dibatasi frame/audio packet. Center crop bukan face tracking.
- Subtitle ASR dan caption AI perlu ditinjau manusia, terutama nama, ironi dan sarkasme. Kebenaran isi sumber tidak diverifikasi otomatis.
- yt-dlp tetap dapat terhalang ketersediaan, login atau pembatasan platform. Tidak ada bypass DRM, paywall atau login.

## Akses jaringan (opsional)

Default hanya localhost. Untuk perangkat lain pada jaringan tepercaya/Tailscale:

```bash
.venv/bin/python app.py --host 0.0.0.0 --allow-network --username your-name
```

Password acak dibuat di `data/network-password.txt` dengan izin `0600`. Login Basic diperlukan untuk klien non-loopback; Host/Origin tetap divalidasi dan proxy headers tidak dipercaya. Gunakan alamat IP server dan port8787. Tidak ada TLS, router forwarding atau firewall Windows yang dikonfigurasi otomatis. Preferensikan Tailscale karena Basic di HTTP biasa tidak terenkripsi. Jangan ekspos aplikasi ini langsung ke internet publik. Mode single-user, bukan multi-tenant.

`--allow-weak-password` tersedia hanya sebagai opt-in eksplisit (minimum enam karakter), tetapi tidak direkomendasikan. Default minimum enam belas karakter.

## Pengujian

```bash
.venv/bin/python -m pytest tests -q
node --check static/app.js
node tests/frontend_upgrades.cjs
```

Tes memblokir jaringan eksternal dan panggilan provider nyata. Video, audio dan transkrip fixture dihasilkan secara **sintetis**, bukan data pengguna. Tes FFmpeg menjalankan render dan full decode nyata, pemeriksaan piksel subtitle/judul, Range, ZIP, serta validasi keamanan. HTTP stub bukan bukti layanan provider live.

## Struktur

- `app.py`: FastAPI, antrean, cache, render, file serving dan autentikasi jaringan.
- `subtitles.py`: cue ASS yang dibatasi dan highlight dari timing kata.
- `captions.py`: Groq/Gemini/template lokal dengan kegagalan eksplisit.
- `static/`: dashboard tanpa framework/CDN.
- `tests/`: tes offline dan render sintetis.
- `vendor/youtube-clipper/`: kode upstream dan adaptasi Deepgram, beserta lisensinya.
- `data/`: dibuat saat runtime; **tidak masuk Git**.

Tidak disertakan: API key, password, media pengguna, transkrip pengguna, job history, virtualenv, atau artefak pengujian lokal.

## Atribusi

Berdasarkan [op7418/Youtube-clipper-skill](https://github.com/op7418/Youtube-clipper-skill), berlisensi MIT. Lisensi upstream dipertahankan di `vendor/youtube-clipper/LICENSE`; adaptasi Deepgram dan dashboard memiliki atribusi di `THIRD_PARTY_NOTICES.md`.
