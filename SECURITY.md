# Keamanan AutoClipper

## Model penggunaan

AutoClipper ditujukan untuk **satu ruang kerja lokal** atau akses terbatas dari jaringan privat tepercaya. Ini bukan layanan multi-tenant dengan isolasi akun, bukan layanan publik siap-produksi, dan tidak menyediakan TLS bawaan.

- Default server hanya mendengarkan localhost.
- Akses jaringan memerlukan `--allow-network`; bind `0.0.0.0` membuka semua interface IPv4 yang tersedia.
- Klien non-loopback wajib autentikasi Basic. Klien loopback tidak diwajibkan login ini; pengguna/proses lokal tetap bagian dari batas kepercayaan.
- Mode default memakai password acak dalam file berizin `0600`, minimum 16 karakter. `--allow-weak-password` adalah opt-in eksplisit, bukan default, dan tidak direkomendasikan.
- Host/Origin divalidasi dan proxy headers tidak dipercaya. Jangan menonaktifkan pengaman ini agar domain/proxy sembarang bekerja.

**Jangan mengekspos aplikasi langsung ke internet publik atau membuat router port-forward tanpa penilaian keamanan terpisah.** Basic Auth di HTTP biasa tidak mengenkripsi kredensial. Untuk perangkat lain, pilih jaringan privat terenkripsi seperti Tailscale, batasi ACL/firewall, dan tetap gunakan autentikasi aplikasi. Tailscale tidak otomatis menyediakan HTTPS pada aplikasi. Terminasi TLS/domain reverse proxy dapat memerlukan penyesuaian karena pemeriksaan origin bawaan menggunakan HTTP/IP.

## Rahasia dan data sensitif

- Simpan API key hanya di environment proses server atau `.env` pada root checkout. Jangan menaruh key di frontend, URL, parameter query, Git, issue, screenshot, atau chat.
- `.env.example` harus tetap tanpa kredensial. Lindungi `.env` dan file password dengan izin `0600` pada filesystem Linux yang mendukungnya.
- Jangan commit `data/`, password file, video/audio, transkrip, riwayat job, atau artefak pengujian lokal. Periksa kembali perubahan sebelum push; `.gitignore` bukan pemindai kebocoran rahasia.
- Backup dan salinan ZIP/manifest dapat berisi informasi sumber/hasil. Batasi akses seperti data aslinya.
- Transkripsi berjalan lokal dengan faster-whisper; audio tidak pernah dikirim ke pihak ketiga. Caption Groq/Gemini mengirim transkrip klip serta konteks sumber. Tinjau persetujuan subjek data dan kebijakan provider.
- Menghapus proyek/output **tidak berarti cache sumber/transkrip ikut terhapus**, dan tidak menghapus data yang sudah diterima provider atau diunduh pihak lain.

Jika rahasia bocor, **cabut/rotasi di provider terlebih dahulu**, hentikan akses yang terdampak, lalu bersihkan salinan dan riwayat yang relevan. Menghapus satu file atau commit baru saja tidak membatalkan key yang sudah terungkap.

## Melaporkan kerentanan

Laporkan secara **privat kepada pemilik repository melalui GitHub**. Jika fitur GitHub Private Vulnerability Reporting tersedia pada repository, gunakan jalur tersebut; jika tidak, hubungi pemilik melalui kanal privat yang disepakati. Jangan membuat issue publik berisi eksploit, key, password, alamat privat, atau media/transkrip pengguna. Tidak ada alamat email pelaporan khusus yang diumumkan di dokumen ini.

Sertakan:

- Ringkasan dampak dan prasyarat serangan.
- Commit/versi yang diperiksa serta lingkungan yang relevan.
- Langkah reproduksi minimal memakai data sintetis/berizin.
- Bukti yang sudah disanitasi dan, jika ada, usulan mitigasi.

Jangan mengakses data orang lain atau menguji instance pihak lain tanpa izin. Dokumentasi ini tidak menjanjikan bug bounty, SLA respons, audit keamanan penuh, atau dukungan versi tertentu.
