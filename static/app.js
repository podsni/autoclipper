'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const activeStatuses = new Set(['queued', 'downloading', 'transcribing', 'selecting', 'rendering']);
  const statusLabels = { queued: 'Dalam antrean', downloading: 'Mengunduh video', transcribing: 'Mentranskripsi audio', selecting: 'Memilih potongan', rendering: 'Merender klip', completed: 'Selesai', failed: 'Gagal' };
  const state = { jobs: [], selected: null, timer: null, polling: false, submitting: false, configured: null, rendered: null };
  let toastTimer;

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  // Media and downloads must stay on this server. Never trust URLs in job data.
  function localURL(value) {
    if (typeof value !== 'string' || !value.trim()) return null;
    try {
      const url = new URL(value, location.href);
      return ['http:', 'https:'].includes(url.protocol) && url.origin === location.origin && !url.username && !url.password ? url.href : null;
    } catch { return null; }
  }
  function clock(value) {
    const number = Number(value);
    if (!Number.isFinite(number) || number < 0) return '—';
    const seconds = Math.floor(number);
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return (hours ? `${hours}:` : '') + String(minutes).padStart(2, '0') + ':' + String(seconds % 60).padStart(2, '0');
  }
  function dateLabel(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '' : new Intl.DateTimeFormat('id-ID', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }).format(date);
  }
  async function api(path, options = {}) {
    const controller = new AbortController();
    const { timeoutMs = 20000, ...fetchOptions } = options;
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(path, { ...fetchOptions, signal: controller.signal, headers: { Accept: 'application/json', ...options.headers } });
      let data;
      try { data = await response.json(); } catch { throw new Error('Respons layanan tidak terbaca. Coba muat ulang.'); }
      if (!response.ok) {
        const detail = data.message || data.error || data.detail;
        throw new Error(typeof detail === 'string' ? detail : `Permintaan gagal (${response.status}).`);
      }
      return data;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('Layanan terlalu lama merespons. Muat ulang riwayat untuk memeriksa status sebelum mencoba lagi.');
      if (error instanceof TypeError) throw new Error('Tidak dapat terhubung ke layanan lokal. Pastikan server berjalan, lalu muat ulang.');
      throw error;
    } finally { clearTimeout(timeout); }
  }
  function networkError(message = '') {
    $('network-message').textContent = message;
    $('network-message').hidden = !message;
  }
  function updateCreateButton() {
    $('create-button').disabled = state.submitting || state.configured === false;
    $('create-button').textContent = state.submitting ? 'Mengirim…' : 'Buat klip ↗';
  }
  async function health() {
    try {
      const data = await api('/api/health');
      state.configured = data.status === 'ok' && data.deepgram_configured === true;
      $('health-state').textContent = state.configured ? '● Layanan siap · Deepgram terhubung' : 'Deepgram belum siap. Konfigurasikan API key di server.';
      $('health-state').classList.toggle('warning', !state.configured);
    } catch {
      state.configured = false;
      $('health-state').textContent = 'Layanan belum terhubung. Coba muat ulang.';
      $('health-state').classList.add('warning');
    }
    updateCreateButton();
  }
  function updateJob(job) {
    if (!job || typeof job.id !== 'string') throw new Error('Data proyek dari server tidak valid.');
    const index = state.jobs.findIndex(item => item.id === job.id);
    if (index < 0) state.jobs.unshift(job);
    else state.jobs[index] = job;
  }
  function renderProjects() {
    const select = $('project-select');
    select.replaceChildren();
    select.disabled = !state.jobs.length;
    if (!state.jobs.length) select.append(element('option', '', 'Belum ada proyek'));
    for (const job of state.jobs) {
      const option = element('option', '', [job.title || 'Video YouTube', statusLabels[job.status] || 'Status tidak dikenal', dateLabel(job.created_at)].filter(Boolean).join(' · '));
      option.value = job.id;
      option.selected = job.id === state.selected;
      select.append(option);
    }
  }
  function downloadLink(label, value, className = 'button secondary') {
    const url = localURL(value);
    if (!url) return null;
    const link = element('a', className, label);
    link.href = url;
    link.setAttribute('download', '');
    return link;
  }
  function toast(message) {
    clearTimeout(toastTimer);
    $('copy-status').textContent = message;
    $('copy-status').hidden = false;
    toastTimer = setTimeout(() => { $('copy-status').hidden = true; }, 3500);
  }
  async function copyCaption(text, button) {
    let copied = false;
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(text);
      copied = true;
    } catch {
      const field = element('textarea');
      field.value = text;
      field.setAttribute('readonly', '');
      field.setAttribute('aria-label', 'Teks caption untuk disalin');
      field.style.cssText = 'position:fixed;left:-9999px;top:0';
      document.body.append(field);
      field.select();
      try { copied = document.execCommand('copy'); } catch { /* Manual selection remains available in caption. */ }
      field.remove();
      button.focus({ preventScroll: true });
    }
    toast(copied ? 'Caption disalin.' : 'Tidak dapat menyalin otomatis. Pilih teks caption lalu salin secara manual.');
  }
  function captionDraft(clip, jobId) {
    const panel = element('section', 'caption-draft');
    panel.append(element('h4', '', 'Draf caption Shorts / TikTok'));
    const note = element('p', 'field-help', 'Groq (utama) / Gemini (opsional): transkrip klip dikirim ke API berbayar saat tombol ditekan. Lokal: template berbasis transkrip, bukan AI; tanpa biaya API.');
    panel.append(note);
    const controls = element('div', 'caption-controls');
    function select(label, options) {
      const wrapper = element('label', '', label);
      const input = element('select');
      input.setAttribute('aria-label', label);
      for (const [value, text] of options) {
        const option = element('option', '', text); option.value = value; input.append(option);
      }
      input.value = options[0][0];
      wrapper.append(input); controls.append(wrapper); return input;
    }
    const platform = select('Platform caption', [['Shorts', 'YouTube Shorts'], ['TikTok', 'TikTok']]);
    const style = select('Gaya caption', [['singkat', 'Singkat'], ['informatif', 'Informatif'], ['pertanyaan', 'Pertanyaan']]);
    panel.append(controls);
    const actions = element('div', 'caption-actions');
    const groq = element('button', 'button primary', 'Buat dengan Groq');
    const gemini = element('button', 'button secondary', 'Buat dengan Gemini');
    const local = element('button', 'button secondary', 'Buat draf lokal');
    groq.type = gemini.type = local.type = 'button';
    groq.disabled = gemini.disabled = local.disabled = !(clip.caption || clip.title);
    actions.append(groq, gemini, local);
    const resultTitle = element('p', 'draft-title');
    const editor = element('textarea', 'caption-editor');
    editor.rows = 7; editor.setAttribute('aria-label', 'Draf caption yang dapat diedit');
    editor.placeholder = 'Pilih platform dan gaya, lalu buat draf. Hasil dapat diedit sebelum disalin.';
    const status = element('p', 'field-help'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    const resultActions = element('div', 'caption-actions');
    const copy = element('button', 'button secondary', 'Salin draf');
    const download = element('button', 'button secondary', 'Unduh .txt');
    copy.type = download.type = 'button'; copy.disabled = download.disabled = true;
    function updateActions() { copy.disabled = download.disabled = !editor.value.trim(); }
    editor.addEventListener('input', updateActions);
    copy.addEventListener('click', () => copyCaption(editor.value, copy));
    download.addEventListener('click', () => {
      const blob = new Blob([editor.value], { type: 'text/plain;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = element('a'); link.href = url; link.download = 'caption-' + platform.value.toLowerCase() + '.txt';
      document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    async function generate(provider) {
      if (groq.disabled) return;
      groq.disabled = gemini.disabled = local.disabled = true;
      platform.disabled = style.disabled = true;
      status.textContent = provider !== 'local-template' ? `Meminta draf ${provider === 'groq' ? 'Groq' : 'Gemini'}… tunggu hingga 120 detik. Tidak ada retry otomatis.` : 'Menyusun template lokal…';
      panel.setAttribute('aria-busy', 'true');
      try {
        const data = await api(`/api/jobs/${encodeURIComponent(jobId)}/clips/${encodeURIComponent(clip.id)}/caption`, { method: 'POST', timeoutMs: 130000, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ platform: platform.value, style: style.value, provider }) });
        if (typeof data.text !== 'string' || !data.text.trim()) throw new Error('Draf caption kosong.');
        editor.value = data.text;
        resultTitle.textContent = data.title || '';
        status.textContent = `${data.method === 'groq' ? 'Groq · ' : data.method === 'gemini' ? 'Gemini · ' : 'Template lokal · '}${data.disclaimer || 'Tinjau sebelum dibagikan.'}`;
        updateActions();
      } catch (error) { status.textContent = error.message; }
      finally {
        groq.disabled = gemini.disabled = local.disabled = false; platform.disabled = style.disabled = false;
        panel.setAttribute('aria-busy', 'false');
      }
    }
    groq.addEventListener('click', () => generate('groq'));
    gemini.addEventListener('click', () => generate('gemini'));
    local.addEventListener('click', () => generate('local-template'));
    resultActions.append(copy, download);
    panel.append(actions, resultTitle, editor, status, resultActions);
    return panel;
  }
  function renderClip(clip, index) {
    const card = element('article', 'clip-card');
    const shell = element('div', 'video-shell');
    const videoURL = localURL(clip.video_url);
    if (videoURL) {
      const video = element('video');
      video.controls = true;
      video.preload = 'metadata';
      video.playsInline = true;
      video.src = videoURL;
      video.setAttribute('aria-label', clip.title || `Pratinjau klip ${index + 1}`);
      const poster = localURL(clip.poster_url);
      if (poster) video.poster = poster;
      video.append(document.createTextNode('Browser tidak mendukung pemutar video. Gunakan tautan unduhan MP4.'));
      video.addEventListener('error', () => {
        if (shell.querySelector('.video-error')) return;
        const error = element('p', 'video-error', 'Pratinjau tidak dapat dimuat. Coba unduh MP4.');
        shell.append(error);
      });
      shell.append(video);
    } else shell.append(element('p', 'video-unavailable', 'Pratinjau belum tersedia.'));
    shell.append(element('span', 'clip-index', `KLIP ${String(index + 1).padStart(2, '0')}`));
    const details = element('div', 'clip-details');
    details.append(element('p', 'clip-method', clip.selection_method === 'heuristic' ? 'PILIHAN HEURISTIK' : clip.selection_method === 'manual' ? 'PILIHAN MANUAL' : 'METODE BELUM TERSEDIA'));
    details.append(element('h3', '', clip.title || `Klip ${index + 1}`));
    details.append(element('p', 'clip-time', `${clock(clip.duration)} durasi · Sumber ${clock(clip.start)}–${clock(clip.end)}`));
    const checks = clip.checks || {};
    const passed = [['video', 'video'], ['audio', 'audio'], ['vertical', 'vertikal']].filter(([key]) => checks[key] === true).map(([, label]) => label);
    details.append(element('p', `clip-checks${passed.length ? '' : ' pending'}`, passed.length ? `✓ Terverifikasi: ${passed.join(' · ')}` : 'Pemeriksaan teknis belum tersedia'));
    const caption = element('div', 'caption-box');
    const captionHeading = element('div', 'caption-heading');
    captionHeading.append(element('span', '', 'Caption'));
    const captionText = typeof clip.caption === 'string' ? clip.caption : '';
    const copy = element('button', 'copy-button', 'Salin teks');
    copy.type = 'button';
    copy.disabled = !captionText;
    copy.setAttribute('aria-label', `Salin caption klip ${index + 1}`);
    copy.addEventListener('click', () => copyCaption(captionText, copy));
    captionHeading.append(copy);
    caption.append(captionHeading, element('p', 'caption-text', captionText || 'Caption belum tersedia.'));
    details.append(caption, captionDraft(clip, state.selected));
    const downloads = element('div', 'clip-downloads');
    const mp4 = downloadLink('↓ Video MP4', clip.video_url);
    const subtitle = downloadLink('↓ Subtitle SRT', clip.subtitle_url);
    if (mp4) downloads.append(mp4);
    if (subtitle) downloads.append(subtitle);
    const ass = downloadLink('↓ Subtitle ASS', clip.ass_url);
    if (ass) downloads.append(ass);
    if (!mp4 && !subtitle) downloads.append(element('p', 'muted', 'Unduhan belum tersedia.'));
    details.append(downloads);
    card.append(shell, details);
    return card;
  }
  function renderSelected() {
    const job = state.jobs.find(item => item.id === state.selected);
    const clips = Array.isArray(job?.clips) ? job.clips : [];
    $('clip-total').textContent = String(clips.length);
    $('job-status').hidden = !job;
    $('download-all').hidden = true;
    if (job) {
      const progress = Number.isFinite(Number(job.progress)) ? Math.max(0, Math.min(100, Number(job.progress))) : 0;
      $('job-badge').textContent = statusLabels[job.status] || 'Status tidak dikenal';
      $('job-badge').className = `status-badge ${job.status === 'completed' ? 'completed' : job.status === 'failed' ? 'failed' : ''}`;
      $('job-title').textContent = job.title || 'Video YouTube';
      $('job-source').textContent = [job.channel, dateLabel(job.created_at)].filter(Boolean).join(' · ');
      $('job-percent').textContent = `${Math.round(progress)}%`;
      $('job-progress').value = progress;
      $('job-message').textContent = job.status === 'failed' ? (typeof job.error === 'string' ? job.error : job.message || 'Pemrosesan gagal. Periksa sumber video dan konfigurasi server sebelum membuat proyek baru.') : job.message || job.stage || statusLabels[job.status] || '';
      if (job.status === 'completed' && clips.length) {
        const zip = localURL(job.zip_url || `/api/jobs/${encodeURIComponent(job.id)}/download.zip`);
        if (zip) { $('download-all').href = zip; $('download-all').hidden = false; }
      }
    }
    // Preserve playback, focus and caption selection when only progress changed.
    const signature = JSON.stringify([job?.id, clips]);
    if (signature !== state.rendered) {
      $('clips-grid').replaceChildren(...clips.map(renderClip));
      state.rendered = signature;
    }
    $('empty-state').hidden = clips.length > 0;
    const emptyHeading = $('empty-state').querySelector('h3');
    const emptyText = $('empty-state').querySelector('p');
    emptyHeading.textContent = !job ? 'Ruang untuk cerita berikutnya.' : job.status === 'failed' ? 'Proyek ini belum menghasilkan klip.' : job.status === 'completed' ? 'Tidak ada klip pada proyek ini.' : 'Videomu sedang diolah.';
    emptyText.textContent = !job ? 'Belum ada klip. Tambahkan tautan di atas untuk memulai. Hasil asli dan subtitle akan tampil di sini setelah diproses.' : activeStatuses.has(job.status) ? 'Klip akan muncul setelah tersedia. Kamu boleh memuat ulang halaman; riwayat tersimpan di server lokal.' : 'Lihat status proyek di atas. Kamu bisa membuat proyek baru dari formulir.';
    $('empty-state').querySelector('a').hidden = !!job && activeStatuses.has(job.status);
  }
  function schedulePoll() {
    clearTimeout(state.timer);
    if (state.jobs.some(job => activeStatuses.has(job.status))) state.timer = setTimeout(poll, 2000);
  }
  async function poll() {
    if (state.polling) return;
    state.polling = true;
    try {
      await Promise.all(state.jobs.filter(job => activeStatuses.has(job.status)).map(async job => {
        updateJob(await api(`/api/jobs/${encodeURIComponent(job.id)}`));
      }));
      networkError();
      renderProjects();
      renderSelected();
    } catch (error) { networkError(`${error.message} Status terakhir tetap ditampilkan.`); }
    finally { state.polling = false; schedulePoll(); }
  }
  async function loadJobs() {
    $('refresh-button').disabled = true;
    try {
      const data = await api('/api/jobs');
      if (!Array.isArray(data.jobs)) throw new Error('Riwayat proyek tidak valid.');
      state.jobs = data.jobs.filter(job => job && typeof job.id === 'string');
      if (!state.jobs.some(job => job.id === state.selected)) state.selected = state.jobs[0]?.id || null;
      networkError();
      renderProjects();
      renderSelected();
    } catch (error) {
      networkError(error.message);
      if (!state.jobs.length) { renderProjects(); renderSelected(); }
    } finally { $('refresh-button').disabled = false; schedulePoll(); }
  }
  $('project-select').addEventListener('change', event => {
    state.selected = event.target.value;
    renderSelected();
  });
  $('refresh-button').addEventListener('click', () => { health(); loadJobs(); });
  $('create-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (state.submitting) return;
    $('form-message').textContent = '';
    let source;
    try { source = new URL($('video-url').value.trim()); } catch { $('form-message').textContent = 'Masukkan tautan YouTube yang valid.'; return; }
    const host = source.hostname.toLowerCase();
    if (!['https:', 'http:'].includes(source.protocol) || !(host === 'youtu.be' || host === 'youtube.com' || host.endsWith('.youtube.com')) || source.username || source.password) {
      $('form-message').textContent = 'Gunakan tautan youtube.com atau youtu.be yang valid.';
      $('video-url').focus();
      return;
    }
    if (!$('rights').checked || !$('paid').checked) { $('form-message').textContent = 'Konfirmasi hak penggunaan dan persetujuan biaya transkripsi terlebih dahulu.'; return; }
    if (state.configured === false) { $('form-message').textContent = 'Deepgram belum siap. Periksa konfigurasi server dan muat ulang.'; return; }
    state.submitting = true;
    updateCreateButton();
    try {
      const job = await api('/api/jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url: source.href, clip_count: Number($('clip-count').value), language: $('language').value, layout: $('layout').value, subtitle_style: $('subtitle-style').value, render_preset: $('render-preset').value, headline: $('headline').value, rights_confirmed: $('rights').checked, paid_confirmed: $('paid').checked }) });
      updateJob(job);
      state.selected = job.id;
      renderProjects();
      renderSelected();
      schedulePoll();
      $('form-message').textContent = 'Proyek masuk antrean. Perkembangan proses tampil di bawah.';
      // Read back the exact created job; the server owns durable state.
      try { updateJob(await api(`/api/jobs/${encodeURIComponent(job.id)}`)); renderProjects(); renderSelected(); }
      catch (error) { networkError(`Proyek sudah dibuat. ${error.message}`); }
    } catch (error) { $('form-message').textContent = error.message; }
    finally { state.submitting = false; updateCreateButton(); }
  });
  window.addEventListener('pagehide', () => clearTimeout(state.timer));
  window.addEventListener('pageshow', event => { if (event.persisted) { health(); loadJobs(); } });
  health();
  loadJobs();
})();
