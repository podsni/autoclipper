# AutoClipper

**Studio web berbahasa Indonesia untuk membuat, meninjau, dan mengunduh klip vertikal dari satu video YouTube berizin.** Tempel URL, minta tiga klip, lalu tinjau hasilnya—bukan layanan auto-post dan bukan jaminan viral.

Pemrosesan video, render, cache, dan riwayat berjalan di mesin sendiri. **Transkripsi berjalan lokal dengan faster-whisper (gratis, tanpa API key)** jika belum tersedia di cache — audio tidak pernah keluar dari mesin ini. Caption Groq/Gemini bersifat opsional; tersedia juga template lokal tanpa panggilan AI.

## Daftar isi

- [Fitur](#fitur)
- [Persyaratan](#persyaratan)
- [Quickstart dari clone baru](#quickstart-dari-clone-baru)
- [Konfigurasi server](#konfigurasi-server)
- [Cara membuat tiga klip](#cara-membuat-tiga-klip)
- [Pengaturan video dan subtitle](#pengaturan-video-dan-subtitle)
- [Caption Groq, Gemini, dan lokal](#caption-groq-gemini-dan-lokal)
- [Progress, riwayat, dan penghapusan](#progress-riwayat-dan-penghapusan)
- [Akses jaringan dan autentikasi](#akses-jaringan-dan-autentikasi)
- [Cache, biaya, dan privasi](#cache-biaya-dan-privasi)
- [Arsitektur dan struktur proyek](#arsitektur-dan-struktur-proyek)
- [Referensi API](#referensi-api)
- [Pengujian dan batas verifikasi](#pengujian-dan-batas-verifikasi)
- [Troubleshooting](#troubleshooting)
- [Hak cipta dan batasan](#hak-cipta-dan-batasan)
- [Atribusi dan keamanan](#atribusi-dan-keamanan)

## Fitur

- Dashboard lokal dengan pengaturan render, preview MP4, pilihan proyek, dan riwayat persisten.
- Antrean **satu worker**; job diproses bergantian, bukan render paralel tanpa batas.
- faster-whisper **small** (lokal, gratis) dengan timestamp kata dan penggunaan ulang transkrip cache.
- Pemilihan potongan tidak tumpang tindih berdasarkan **heuristik kalimat/topik**, bukan penilaian AI atas kebenaran atau potensi viral.
- MP4 **720 × 1280 (9:16), H.264/AAC**, subtitle tertanam, SRT/ASS terpisah, poster, dan arsip ZIP.
- Subtitle **Clean** atau **Highlight** berbasis timestamp kata nyata.
- Preset **Seperti contoh**: judul kuning, gambar utuh, latar blur gelap, subtitle, dan kredit sumber.
- Draf caption Shorts/TikTok dari **Groq**, **Gemini**, atau **template lokal**; dapat diedit, disalin, dan diunduh sebagai TXT.
- Mode jaringan dengan opt-in eksplisit, password acak, autentikasi Basic untuk klien non-loopback, dan pemeriksaan Host/Origin.

**SSE, progress render terukur, dan penghapusan proyek** sudah diimplementasikan. Selain tes offline, alur browser asli telah diuji menggunakan media/transkrip sintetis: render FFmpeg, pembaruan SSE, dialog batal/konfirmasi hapus, pembacaan ulang riwayat, dan cache yang tetap ada. Pengujian ini tidak memanggil provider berbayar.

## Persyaratan

Target penggunaan: **Linux atau WSL**. Jangan mengasumsikan perintah shell berikut berlaku langsung di PowerShell.

| Komponen | Kebutuhan |
| --- | --- |
| Python | **3.13+**, disarankan virtualenv melalui `uv` |
| uv | Pembuatan virtualenv dan instalasi dependensi Python |
| FFmpeg dan FFprobe | Tersedia di `PATH`; FFmpeg harus mendukung `libx264`, AAC, dan filter ASS/libass |
| Font | **DejaVu Sans** untuk render subtitle/judul |
| Node.js | **20+**, tersedia di `PATH` untuk runtime JavaScript/EJS yt-dlp; bukan build frontend |
| Koneksi keluar | YouTube, komponen EJS dari GitHub, serta provider caption yang dipilih (transkripsi berjalan lokal, tanpa koneksi) |
| Ruang disk | Untuk sumber, audio/transkrip, hasil render, dan ZIP; penggunaan bergantung video dan jumlah klip |

Contoh dependensi sistem Ubuntu/Debian/WSL:

```bash
sudo apt update
sudo apt install -y git curl ca-certificates ffmpeg fonts-dejavu-core
```

Pasang **Node.js 20+** melalui metode tepercaya yang sesuai distro. Paket `nodejs` bawaan distro bisa lebih tua; periksa versinya, bukan hanya keberadaan executable.

```bash
node --version
ffmpeg -version
ffprobe -version
fc-match 'DejaVu Sans'
```

Frontend berupa HTML/CSS/JavaScript statis: **tidak perlu `npm install` atau build bundler**. Kode transkripsi yang diperlukan sudah disertakan di `vendor/youtube-clipper/`; tidak perlu clone upstream kedua.

## Quickstart dari clone baru

### 1. Akses repository

Repository `podsni/autoclipper` bersifat **private**. Akun GitHub harus sudah diberi akses; gunakan SSH yang telah terautentikasi:

```bash
git clone git@github.com:podsni/autoclipper.git
cd autoclipper
```

Alternatif HTTPS setelah menyiapkan autentikasi GitHub:

```bash
git clone https://github.com/podsni/autoclipper.git
cd autoclipper
```

Jangan menaruh token GitHub di URL clone atau README. `Repository not found` dapat berarti akun belum memiliki akses, bukan repository publik yang bisa diunduh anonim.

### 2. Pasang uv dan dependensi Python

Jika `uv` belum tersedia, gunakan installer resminya. Tinjau skrip sebelum menjalankannya jika kebijakan mesin mengharuskan:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# Buka ulang shell bila uv belum ditemukan di PATH.
uv --version
uv python install 3.13
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

### 3. Siapkan `.env` di root repository

```bash
cp .env.example .env
chmod 600 .env
# Buka .env memakai editor lokal, lalu isi hanya key yang diperlukan.
```

Isi awalnya sengaja **kosong**:

```dotenv
# WHISPER_MODEL=small
GROQ_API_KEY=
GEMINI_API_KEY=
```

- **Transkripsi lokal** tidak butuh key: model faster-whisper `small` dipakai secara default (diunduh sekali dari Hugging Face bila belum ada di cache). Set `WHISPER_MODEL` ke nama model lain atau direktori model lokal bila perlu.
- **Groq/Gemini** hanya diperlukan jika memakai provider caption tersebut.
- Jangan menyalin tanda placeholder menjadi key sungguhan. Jangan commit `.env`.

### 4. Jalankan lokal

```bash
.venv/bin/python app.py
```

Buka **http://127.0.0.1:8787**. Hentikan server dengan `Ctrl+C`. Direktori `data/` dibuat otomatis. Checkout baru tidak menyertakan video, transkrip, atau riwayat milik pengguna lain.

Pemeriksaan dasar tanpa memulai job:

```bash
curl --fail http://127.0.0.1:8787/api/health
```

`status: "ok"` berarti server merespons. `transcription_configured: true` berarti skrip transkripsi lokal tersedia di checkout — **bukan** bukti model sudah terunduh atau transkripsi akan sukses.

## Konfigurasi server

API key dibaca di **server** dari environment proses atau `.env` di **root checkout ini**, bukan direktori profil developer. Tidak ada input API key publik di browser.

| Variabel | Kegunaan |
| --- | --- |
| `WHISPER_MODEL` | Override model transkripsi (nama faster-whisper atau direktori model lokal); default `small` |
| `GROQ_API_KEY` | Caption Groq opsional |
| `GEMINI_API_KEY` | Caption Gemini opsional |
| `GROQ_CAPTION_MODEL` | Override model Groq melalui **environment proses**; default kode `openai/gpt-oss-20b` |
| `GEMINI_CAPTION_MODEL` | Override model Gemini melalui **environment proses**; default kode `models/gemini-3.8-flash` |

Environment proses mengambil prioritas untuk key yang terisi. **Override model tidak dibaca dari `.env`** oleh modul caption. Default model adalah konfigurasi kode, bukan jaminan model tersedia bagi semua akun atau kuota.

```bash
GROQ_CAPTION_MODEL='openai/gpt-oss-20b' .venv/bin/python app.py
# Contoh lain: export GEMINI_CAPTION_MODEL dengan ID model yang tersedia bagi akun Anda.
```

Lihat opsi CLI aktual dengan `.venv/bin/python app.py --help`. Untuk mengganti port lokal:

```bash
.venv/bin/python app.py --port 8788
```

## Cara membuat tiga klip

1. Tempel URL **satu video YouTube HTTPS** yang Anda miliki atau berhak olah. Playlist dan live stream tidak didukung.
2. Pilih **3 klip**, bahasa audio **Indonesia** atau **English**, gaya subtitle, dan preset video.
3. Opsional: isi **Judul atas**. Jika kosong, judul berasal dari cuplikan teks kandidat transkrip.
4. Centang konfirmasi hak penggunaan. Transkripsi berjalan lokal — tidak ada audio yang dikirim ke pihak ketiga dan tidak ada biaya API.
5. Klik **Buat klip**. Job mengantre, mengunduh sumber bila perlu, mentranskripsi, memilih kandidat, lalu merender dan memeriksa media.
6. Tinjau setiap preview: awal/akhir kalimat, ejaan, konteks, judul, kredit, dan keterbacaan subtitle.
7. Unduh MP4, SRT, ASS, atau seluruh hasil melalui **ZIP**. ZIP juga berisi poster dan manifest job.
8. Jika diperlukan, buat draf caption di kartu klip, edit, lalu salin atau unduh TXT.

Tiga adalah **jumlah yang diminta**, bukan janji pasti. Jika ucapan tidak cukup, hasil dapat lebih sedikit. Aplikasi tidak mengunggah ke YouTube/TikTok secara otomatis.

## Pengaturan video dan subtitle

| Pengaturan | Perilaku |
| --- | --- |
| Jumlah klip | API menerima 1–8; pilihan UI tersedia untuk 1, 3, 5, dan 8 |
| Bahasa audio | `id` atau `en`; memilih bahasa transkripsi, **bukan penerjemahan** |
| Utuh / `fit` | Menjaga seluruh gambar, mengisi ruang vertikal dengan latar blur |
| Penuh / `crop` | Memenuhi frame vertikal dengan crop tengah; **bukan face tracking** |
| Clean / `clean` | Subtitle putih tanpa penyorotan kata aktif |
| Highlight / `highlight` | Kata aktif kuning menggunakan timestamp kata nyata; timing interpolasi tidak diperlakukan sebagai timing kata asli |
| Standar / `standard` | Render mengikuti pilihan fit/crop, tanpa judul atas preset reference |
| Seperti contoh / `reference` | Gambar utuh di tengah, latar blur gelap, judul kuning, subtitle, kredit sumber; **mengabaikan crop** |
| Judul atas / `headline` | Maksimal 120 karakter input, dipadatkan maksimal dua baris; hanya relevan pada preset reference |

Perubahan pengaturan hanya berlaku pada **job/render baru**. Tidak mengubah MP4 yang sudah selesai. Subtitle pada MP4 sudah tertanam; mengedit berkas SRT/ASS hasil unduhan tidak otomatis merender ulang MP4.

## Caption Groq, Gemini, dan lokal

Pada kartu klip, pilih platform **Shorts/TikTok**, gaya **singkat**, **informatif**, atau **pertanyaan**, lalu pilih provider secara eksplisit.

| Provider | Data/pemrosesan | Catatan |
| --- | --- | --- |
| Groq | Transkrip klip dan konteks sumber dikirim ke API Groq | Memerlukan `GROQ_API_KEY`; dapat memakai biaya/kuota |
| Gemini | Transkrip klip dan konteks sumber dikirim ke API Gemini | Memerlukan `GEMINI_API_KEY`; dapat sibuk, timeout, atau tidak tersedia |
| Lokal / `local-template` | Template berbasis transkrip, dikerjakan server lokal | **Bukan AI**, tidak memanggil API caption |

Caption adalah teks unggahan, **berbeda dari subtitle video**. Mengedit caption tidak mengubah subtitle atau judul yang sudah tertanam dalam MP4.

Draf dapat diedit, disalin, dan diunduh sebagai `.txt`. **Simpan TXT sebelum refresh atau berpindah proyek**: edit/draf browser bukan penyimpanan permanen di server. Jika salin tidak diizinkan browser, gunakan seleksi teks manual atau unduh TXT.

Tidak ada retry API berbayar atau pergantian provider/template diam-diam. Kegagalan tetap ditampilkan sebagai kegagalan; pilih provider lain/lokal sendiri. Timeout tidak membuktikan provider belum memproses atau menagih permintaan.

**OpenCode tidak diintegrasikan.** Keterbatasan akses/rate limit free tier bukan alasan untuk mengklaim integrasi tersedia atau beralih diam-diam ke model berbayar.

## Progress, riwayat, dan penghapusan

Riwayat disimpan di `data/jobs.json`. Satu worker menjalankan job secara berurutan. Restart server menandai job yang belum final sebagai **failed/interrupted**; bukan melanjutkan atau membatalkan job secara terdistribusi. Cache yang sudah valid tetap dapat digunakan job baru.

### SSE dan progress realtime

> Persentase render berasal dari encoder nyata. Waktu tunggu provider tidak diubah menjadi persentase simulasi.

- `GET /api/jobs/{job_id}/events` memakai **Server-Sent Events (SSE)**.
- Event bernama **`job`** membawa snapshot job JSON; koneksi mengirim heartbeat saat tidak ada pembaruan dan ditutup setelah status final `completed`/`failed`.
- UI menggunakan SSE untuk job terpilih dan **fallback polling setiap 2 detik** bila stream tidak tersedia.
- Progress render bersumber dari kemajuan **FFmpeg yang benar-benar berjalan**, bukan animasi timer palsu.
- faster-whisper tidak menyediakan kemajuan persentase yang dipakai aplikasi: tahap transkripsi bersifat **indeterminate**.
- Persentase keseluruhan memakai **bobot tahap**, bukan perkiraan waktu selesai/ETA. Angka dapat berhenti sementara selama tahap panjang atau pemeriksaan media.

### Hapus proyek

`DELETE /api/jobs/{job_id}` hanya boleh menghapus job **completed/failed**. Job aktif, termasuk antrean, ditolak dengan **409**. Ini **bukan tombol cancel**.

Penghapusan bersifat permanen untuk **output dan entri riwayat job**: preview, subtitle, poster, manifest, dan ZIP job tidak dapat diunduh lagi. Simpan hasil yang dibutuhkan sebelum menghapus.

**Cache sumber/transkrip tetap disimpan** agar sumber yang sama tidak harus diunduh/transkripsi ulang. Respons sukses memuat `deleted: true` dan `cache_retained: true`; jangan mengartikan tombol hapus proyek sebagai penghapusan seluruh jejak data sumber.

## Akses jaringan dan autentikasi

Default bind adalah **127.0.0.1**, bukan semua interface. Untuk perangkat lain pada jaringan tepercaya atau tailnet:

```bash
.venv/bin/python app.py --host 0.0.0.0 --allow-network --username autoclipper
```

- `0.0.0.0` berarti mendengarkan semua interface IPv4, **bukan alamat yang dibuka di browser**. Gunakan `http://<IP-server>:8787`.
- `--allow-network` wajib untuk bind non-loopback. Mengubah host saja tidak mengaktifkan akses jaringan tanpa pengaman.
- Password acak dibuat sekali di **`data/network-password.txt`**, izin **`0600`**; tidak dicetak ke log. Buka file hanya dengan editor lokal untuk login. File yang sudah ada dipakai kembali.
- `--password-file` dapat memilih file privat lain. Default minimum password **16 karakter**.
- Klien **non-loopback** wajib login Basic. Akses loopback lokal tidak membutuhkan login ini; jangan memakai mesin bersama sebagai batas isolasi pengguna.
- Host/Origin diperiksa; gunakan IP atau localhost yang didukung, bukan mengasumsikan semua domain reverse proxy diterima. Proxy headers tidak dipercaya.

**`--allow-weak-password` adalah opt-in eksplisit**, menurunkan minimum menjadi enam karakter untuk password pilihan pengguna. **Bukan default dan tidak direkomendasikan.** Gunakan password acak yang dibuat aplikasi.

### HTTP, TLS, Tailscale, dan WSL

Aplikasi **tidak menyediakan TLS**. Basic Auth pada HTTP biasa tidak melindungi kredensial dari penyadapan jaringan. Jangan melakukan port forwarding ke internet publik. Pilih jaringan privat terenkripsi seperti **Tailscale**, batasi akses dengan ACL, dan tetap gunakan autentikasi aplikasi untuk klien remote.

Tailscale tidak otomatis mengubah aplikasi menjadi layanan HTTPS. Mode bawaan memeriksa origin HTTP/IP; memasang HTTPS/domain melalui reverse proxy dapat memerlukan perubahan konfigurasi/kode yang **tidak disediakan oleh quickstart ini**. Jangan mengakali pemeriksaan Origin atau mempercayai forwarded headers tanpa meninjau model keamanannya.

Pada **WSL NAT**, bind `0.0.0.0` di Linux belum tentu membuat port dapat diakses dari LAN Windows. Periksa mode jaringan WSL, routing, firewall Windows, dan kebijakan Tailscale. Aplikasi tidak mengonfigurasi firewall, port proxy, router, atau sertifikat secara otomatis. Jangan membuka firewall lebih luas sekadar untuk menghilangkan error koneksi.

## Cache, biaya, dan privasi

| Lokasi/aliran | Isi dan konsekuensi |
| --- | --- |
| `data/cache/<video_id>/` | Sumber, metadata, transkrip dan artefak transkripsi; dipakai ulang berdasarkan ID YouTube |
| `data/outputs/<job_id>/` | MP4, SRT/ASS, poster, manifest dan ZIP job |
| `data/jobs.json` | URL, pengaturan, status, dan riwayat job lokal |
| faster-whisper (lokal) | Tidak mengirim audio ke mana pun; seluruh transkripsi berjalan di mesin ini |
| Groq/Gemini | Menerima transkrip klip serta konteks judul/atribusi saat provider itu dipilih |
| Template caption lokal | Tidak mengirim permintaan ke provider caption; tidak membuat transkripsi baru menjadi offline |

Mengubah jumlah klip/preset dapat menggunakan ulang sumber dan transkrip sehingga tidak perlu STT ulang. **Cache berdasarkan ID, bukan bahasa**: mengubah pilihan bahasa tidak menerjemahkan atau otomatis mengganti transkrip lama.

Tidak ada jaminan biaya nol, kuota gratis, retry gratis, atau penghapusan data di pihak provider. Tinjau harga, saldo, dan kebijakan retensi provider yang digunakan. Audio/video dapat mengandung data pribadi; dapatkan persetujuan yang diperlukan sebelum mengirimkannya.

Tidak ada UI purge cache yang dijanjikan oleh penghapusan proyek. Jika perlu membersihkan cache, hentikan server dan kelola direktori cache yang benar secara manual setelah backup; transkripsi berikutnya akan berjalan ulang secara lokal (gratis, tetapi butuh waktu). Lindungi backup `data/` seperti data asli. Jangan commit media, transkrip, password, atau riwayat.

## Arsitektur dan struktur proyek

```text
Browser: static/index.html + app.js + styles.css
    │ API same-origin; preview/download dari server sendiri
    ▼
FastAPI / app.py ── jobs.json + antrean satu worker
    │
    ├─ yt-dlp + Node/EJS ── YouTube ── cache sumber
    ├─ faster-whisper (lokal) ── model small ── cache transkrip
    ├─ heuristik kandidat ── subtitles.py ── FFmpeg render
    │                                      └─ FFprobe + full decode
    └─ captions.py ── Groq / Gemini / template lokal
```

```text
autoclipper/
├── app.py                         # API, antrean, cache, render, autentikasi
├── captions.py                    # Draf caption provider/lokal
├── subtitles.py                   # Cue ASS, highlight, judul/kredit
├── static/                        # UI tanpa framework/CDN
├── tests/                         # Tes offline dan render sintetis
├── vendor/youtube-clipper/
│   ├── LICENSE                    # Lisensi MIT upstream
│   └── scripts/                   # Skrip upstream + transkripsi faster-whisper lokal
├── requirements.txt               # Dependensi Python yang dipin
├── .env.example                   # Nama key, tanpa kredensial
├── .env                           # Buat lokal; tidak masuk Git
├── data/                          # Dibuat runtime; tidak masuk Git
├── THIRD_PARTY_NOTICES.md
└── SECURITY.md
```

Server bukan platform multi-tenant: pengguna yang bisa mengaksesnya berada di ruang kerja yang sama. Jangan menjalankan banyak worker Uvicorn terhadap store JSON/antrean ini.

## Referensi API

Base URL lokal: `http://127.0.0.1:8787`. Tidak ada API key provider di payload browser. Mode jaringan memakai autentikasi yang sama dengan UI. Endpoint mutasi dengan body memakai `Content-Type: application/json`; field tidak dikenal ditolak oleh skema request. Swagger/OpenAPI publik tidak diaktifkan.

| Metode dan path | Hasil/perilaku |
| --- | --- |
| `GET /api/health` | Status server dan ketersediaan transkripsi lokal; bukan uji model |
| `GET /api/jobs` | `{ "jobs": [...] }`, terbaru lebih dahulu |
| `POST /api/jobs` | **202**, snapshot job yang diterima antrean; belum berarti render sukses |
| `GET /api/jobs/{job_id}` | Snapshot status, stage, progress, pesan, dan daftar klip; **404** jika tidak ada |
| `GET /api/jobs/{job_id}/events` | SSE event `job`, snapshot JSON, heartbeat, ditutup setelah status final |
| `DELETE /api/jobs/{job_id}` | Hapus hanya completed/failed; **409** bila aktif, **404** bila tidak ada |
| `POST /api/jobs/{job_id}/clips/{clip_id}/caption` | Draf caption; kegagalan provider eksplisit, tanpa fallback otomatis |
| `GET /api/jobs/{job_id}/files/{filename}` | Berkas output yang diizinkan job; MP4 mendukung permintaan Range |
| `GET /api/jobs/{job_id}/download.zip` | Arsip job completed; **404** jika belum siap/tidak ada |

### Membuat job

Contoh body berikut adalah **skema permintaan**, bukan log/data pengguna. Ganti URL placeholder dengan video berizin sebelum mengirim; permintaan valid dapat memulai proses unduh dan render.

```json
{
  "url": "https://www.youtube.com/watch?v=<VIDEO_ID_11_KARAKTER>",
  "clip_count": 3,
  "language": "id",
  "layout": "fit",
  "subtitle_style": "highlight",
  "render_preset": "reference",
  "headline": "",
  "rights_confirmed": true
}
```

`url`, `clip_count`, `language`, `layout`, dan persetujuan hak penggunaan wajib. Persetujuan harus boolean `true`. `clip_count` integer 1–8. Default API: `subtitle_style: clean`, `render_preset: standard`, `headline: ""`; UI dapat memilih default berbeda. URL harus satu video HTTPS dari host YouTube yang didukung, ID tepat 11 karakter yang diizinkan; playlist ditolak. Validasi request gagal dengan **422**.

### Caption

```json
{
  "platform": "Shorts",
  "style": "informatif",
  "provider": "groq"
}
```

`platform`: `Shorts`/`TikTok`; `style`: `singkat`/`informatif`/`pertanyaan`; `provider`: `groq`/`gemini`/`local-template` (default API `groq`). Respons memuat `text`, `title`, `platform`, `style`, `method`, `disclaimer`, dan `model` untuk provider AI.

### Penghapusan dan SSE

Body respons sukses penghapusan **memuat**:

```json
{ "deleted": true, "cache_retained": true }
```

Kedua endpoint ini diimplementasikan dan dicakup tes backend serta browser sintetis. Penghapusan tidak membatalkan job aktif. Konsumen SSE membaca `event: job` dan mengurai `data` sebagai snapshot JSON; heartbeat bukan snapshot baru dan bukan ukuran kemajuan provider.

Kode umum: **401** login jaringan, **403** Host/Origin, **415** body POST bukan JSON, **422** validasi, **429** rate limit provider, **502** kegagalan/kredensial/format respons provider, **503** provider belum dikonfigurasi atau sedang sibuk, **504** timeout caption. Kesalahan pemrosesan job asinkron muncul pada status `failed`, bukan mengubah respons awal 202.

## Pengujian dan batas verifikasi

Jalankan setelah instalasi dependensi sistem/Python:

```bash
.venv/bin/python -m pytest tests -q
node --check static/app.js
node tests/frontend_upgrades.cjs
```

**Tes offline/sintetis** menggunakan fixture media/transkrip buatan dan stub provider; jaringan eksternal serta panggilan provider nyata diblokir. Tes render menjalankan FFmpeg dan full decode nyata, bukan hanya memeriksa keberadaan file. Suite juga mencakup validasi, keamanan akses, file/Range, ZIP, dan perilaku frontend sesuai tes yang ada.

Pisahkan bukti berikut saat melaporkan hasil:

| Pemeriksaan | Yang dibuktikan | Yang tidak dibuktikan |
| --- | --- | --- |
| Pytest + fixture/stub | Perilaku kode terhadap skenario tes, termasuk render lokal bila dependensi tersedia | Validitas key, tagihan, ketersediaan model/provider live |
| `node --check` | Sintaks JavaScript dapat diparse | UI benar secara visual di semua browser |
| Tes frontend Node | Perilaku yang dicakup harness | Pengujian browser penuh atau akses jaringan WSL nyata |
| `/api/health` | Server hidup dan key terdeteksi | Transkripsi/caption berhasil secara live |
| Uji end-to-end live | Alur tertentu berhasil pada saat dan akun yang diuji | SLA, bebas rate limit, bebas biaya, atau keberhasilan semua video |

Uji live memerlukan **izin konten dan persetujuan biaya terpisah**. README ini tidak mengklaim jumlah tes lulus, hasil live provider, CI aktif, maupun URL deployment. Gunakan output eksekusi pada checkout Anda sebagai bukti; jangan menyamakan respons stub dengan keberhasilan API sungguhan.

## Troubleshooting

| Gejala | Pemeriksaan/tindakan |
| --- | --- |
| Clone private gagal / `Repository not found` | Pastikan akun mendapat akses `podsni/autoclipper`; periksa autentikasi SSH/HTTPS tanpa menaruh token di URL |
| `uv` atau Python tidak ditemukan | Buka ulang shell setelah instalasi; jalankan `uv --version`, kemudian `uv python install 3.13` dan buat `.venv` |
| `ffmpeg`/`ffprobe` tidak ada atau filter ASS gagal | Instal paket sistem, periksa `PATH`, dukungan libass/libx264/AAC, dan font DejaVu Sans |
| Transkripsi lokal belum siap | Periksa health dan pastikan `vendor/youtube-clipper/scripts/whisper_transcribe.py` ada di checkout; pastikan `faster-whisper` terinstal (`pip install -r requirements.txt`) |
| Caption **503** | Bedakan key belum dikonfigurasi dengan provider sedang sibuk. Periksa pesan; Gemini dapat 503 meski daftar model bisa diakses. Pilih lokal/provider lain secara eksplisit |
| Caption **429** | Kuota/rate limit provider; tunggu dan periksa dashboard kuota. Jangan spam klik karena tidak ada jaminan bebas biaya |
| **401** saat membuka studio dari perangkat lain | Gunakan username CLI dan password file lokal yang benar; Basic Auth berlaku untuk klien non-loopback |
| Pesan provider **HTTP 401** | Key provider ditolak; API caption dapat memetakan ini ke **502**. Periksa key/izin di server, jangan menempelkannya ke browser atau issue |
| **403** Host/Origin | Buka origin HTTP localhost/IP yang sesuai. Domain/proxy/HTTPS sembarang tidak otomatis didukung; jangan menonaktifkan pemeriksaan |
| yt-dlp gagal / tantangan JavaScript | Pastikan `node --version` ≥20 dan server melihat `node` di PATH; cek koneksi YouTube dan GitHub EJS. Periksa ketersediaan video; login/DRM/paywall tidak dibypass |
| URL ditolak | Gunakan satu URL video HTTPS, tanpa playlist atau ID rusak. Jangan memasukkan channel, pencarian, atau tautan live |
| Progress tampak diam | Transkripsi bersifat indeterminate; antrean dan full decode juga membutuhkan waktu. Periksa pesan stage sebelum membuat job duplikat |
| SSE tidak tersambung | UI fallback polling 2 detik. Periksa koneksi, autentikasi dan buffering proxy; jangan menganggap putus stream berarti job batal |
| Hapus mendapat **409** | Job masih aktif. Tunggu completed/failed; endpoint ini bukan cancel |
| Lebih sedikit klip dari permintaan | Durasi/ucapan tidak menyediakan cukup kandidat tidak tumpang tindih; tinjau sumber, bukan mengasumsikan render hilang |
| Bahasa tidak berubah setelah job baru | Transkrip cache berdasarkan ID dipakai ulang, bukan diterjemahkan. Bersihkan cache secara sadar biaya jika perlu transkripsi ulang |
| Subtitle menimpa gambar / konteks salah | Pilih preset/gaya untuk render baru; tinjau manual. Center crop tidak mengikuti wajah dan ASR bukan editor manusia |
| LAN tidak dapat membuka server WSL | Cek `--host 0.0.0.0 --allow-network`, IP yang benar, WSL NAT/mirrored networking, firewall Windows, routing dan ACL tailnet |
| Server restart di tengah job | Job non-final ditandai failed/interrupted; buat job baru setelah meninjau cache dan kemungkinan panggilan berbayar sebelumnya |
| Copy caption gagal | Clipboard browser dapat memerlukan konteks aman/izin. Unduh TXT atau salin teks manual; jangan menganggap edit sudah tersimpan |

Pesan kegagalan job sengaja tidak menampilkan body error provider, rahasia, atau path lokal. Saat melaporkan masalah, sertakan tahap/status, langkah reproduksi, versi dependensi, dan log yang sudah disanitasi—bukan `.env`, password, atau transkrip pribadi.

## Hak cipta dan batasan

- Gunakan hanya konten milik sendiri atau dengan izin yang sesuai. Dapat diakses publik tidak sama dengan berizin untuk diunduh, dipotong, atau diunggah ulang. Kredit sumber tidak menggantikan izin.
- Maksimum sumber **satu jam**, bukan live stream; maksimum **delapan klip per job**. Batas unduhan dan timeout tetap dapat menggagalkan sumber besar/lambat.
- Kandidat biasanya menargetkan sekitar 30–60 detik ketika ucapan memungkinkan; sumber singkat bisa menghasilkan fallback lebih pendek. Tidak ada jaminan jumlah/durasi persis.
- Pemilihan berbasis heuristik; tidak memahami seluruh konteks, memverifikasi fakta, menjamin viral, atau memastikan potongan aman dipublikasikan.
- Ketepatan potongan dibatasi frame/audio packet. Subtitle ASR dapat salah; highlight membutuhkan timing kata nyata. Periksa nama, kutipan, ironi, sarkasme, dan atribusi.
- Provider dapat mengenakan biaya, menolak key/model, mengalami 429/503, atau timeout. yt-dlp dapat terhalang perubahan platform, pembatasan wilayah, login, atau ketersediaan video.
- Bukan alat bypass DRM, paywall, atau autentikasi. Skrip upstream yang disertakan tidak berarti semua kemampuan upstream tersedia di website.
- Bukan layanan publik siap-produksi, sistem multi-user terisolasi, atau sistem dengan pembatalan/resume job aktif.

## Atribusi dan keamanan

Berdasarkan [op7418/Youtube-clipper-skill](https://github.com/op7418/Youtube-clipper-skill). **Lisensi MIT upstream dipertahankan** di [`vendor/youtube-clipper/LICENSE`](vendor/youtube-clipper/LICENSE); rincian adaptasi tercantum di [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

Panduan menjaga rahasia dan pelaporan masalah keamanan: [`SECURITY.md`](SECURITY.md). Repository tidak menyertakan API key, password, media/transkrip pengguna, job history, virtualenv, atau hasil uji lokal.
