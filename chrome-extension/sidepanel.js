const ACCEPTED_TYPES = ['.wav', '.mp3', '.mp4', '.m4a', '.ogg', '.flac'];
const MAX_HISTORY = 20;

let activeRun = null;

// DOM elements
const dropZone = document.getElementById('dropZone');
const browseBtn = document.getElementById('browseBtn');
const fileInput = document.getElementById('fileInput');
const progressSection = document.getElementById('progressSection');
const progressFilename = document.getElementById('progressFilename');
const progressRingFill = document.getElementById('progressRingFill');
const progressPct = document.getElementById('progressPct');
const progressStatus = document.getElementById('progressStatus');
const cancelBtn = document.getElementById('cancelBtn');
const resultSection = document.getElementById('resultSection');
const resultHero = document.getElementById('resultHero');
const resultHeroImg = document.getElementById('resultHeroImg');
const resultTitle = document.getElementById('resultTitle');
const resultChannel = document.getElementById('resultChannel');
const resultPlatform = document.getElementById('resultPlatform');
const resultDuration = document.getElementById('resultDuration');
const resultMetaRow = document.getElementById('resultMetaRow');
const resultFilename = document.getElementById('resultFilename');
const warningBanner = document.getElementById('warningBanner');
const transcriptBox = document.getElementById('transcriptBox');
const copyBtn = document.getElementById('copyBtn');
const downloadBtn = document.getElementById('downloadBtn');
const newBtn = document.getElementById('newBtn');
const errorMsg = document.getElementById('errorMsg');
const historyList = document.getElementById('historyList');
const openSettings = document.getElementById('openSettings');
const urlSection = document.getElementById('urlSection');
const urlInput = document.getElementById('urlInput');
const urlSubmitBtn = document.getElementById('urlSubmitBtn');

// Settings
openSettings.addEventListener('click', () => {
  chrome.runtime.openOptionsPage();
});

// Drag and drop
dropZone.addEventListener('dragover', (e) => {
  e.preventDefault();
  dropZone.classList.add('drag-over');
});

dropZone.addEventListener('dragleave', () => {
  dropZone.classList.remove('drag-over');
});

dropZone.addEventListener('drop', (e) => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  const file = e.dataTransfer.files[0];
  if (file) handleFile(file);
});

browseBtn.addEventListener('click', (e) => {
  e.stopPropagation();
  fileInput.click();
});

fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) handleFile(fileInput.files[0]);
  fileInput.value = '';
});

// URL submit
urlSubmitBtn.addEventListener('click', () => {
  const url = urlInput.value.trim();
  if (url) handleUrl(url);
});
urlInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    const url = urlInput.value.trim();
    if (url) handleUrl(url);
  }
});

// URL requests through the background script cannot be aborted. Stop only our wait.
cancelBtn.addEventListener('click', () => {
  stopRun();
  showState('input');
});

// Result actions
copyBtn.addEventListener('click', () => {
  navigator.clipboard.writeText(transcriptBox.textContent).then(() => {
    const original = copyBtn.textContent;
    copyBtn.textContent = 'Copied!';
    setTimeout(() => { copyBtn.textContent = original; }, 1500);
  });
});

downloadBtn.addEventListener('click', () => {
  const text = transcriptBox.textContent;
  const filename = (resultFilename.textContent || 'transcript').replace(/\.[^.]+$/, '') + '.txt';
  const blob = new Blob([text], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
});

newBtn.addEventListener('click', () => {
  stopRun();
  showState('input');
});

// Result hero card
function formatDuration(secs) {
  if (!secs) return '';
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function showResultHero(task) {
  const thumb = task && task.thumbnail_url;
  const title = task && task.title;
  const channel = task && (task.uploader || task.channel);
  const platform = task && task.platform;
  const duration = task && task.duration;

  resultHero.style.display = thumb ? 'block' : 'none';
  resultHeroImg.onerror = () => { resultHero.style.display = 'none'; };
  if (thumb) resultHeroImg.src = thumb;
  else resultHeroImg.removeAttribute('src');

  resultTitle.textContent = title || resultFilename.textContent || 'Transcript';
  resultChannel.textContent = channel || '';

  if (platform || duration) {
    resultMetaRow.style.display = 'flex';
    resultPlatform.textContent = platform || '';
    resultPlatform.style.display = platform ? 'inline-flex' : 'none';
    resultDuration.textContent = duration ? formatDuration(duration) : '';
  } else {
    resultMetaRow.style.display = 'none';
  }
}

// State management
function showState(state) {
  dropZone.style.display = state === 'input' ? 'flex' : 'none';
  urlSection.style.display = state === 'input' ? 'block' : 'none';
  progressSection.style.display = state === 'progress' ? 'flex' : 'none';
  resultSection.style.display = state === 'result' ? 'flex' : 'none';
  errorMsg.style.display = 'none';
  warningBanner.style.display = 'none';
  if (state === 'result') {
    resultFilename.style.display = 'none';
  }
}

function showError(msg) {
  errorMsg.textContent = msg;
  errorMsg.style.display = 'block';
}

// Each run owns its controller and timer. Late work can never clear a newer run.
function stopRun() {
  const run = activeRun;
  activeRun = null;
  if (run) {
    clearInterval(run.timer);
    run.controller.abort();
  }
}

function beginRun(kind, filename) {
  stopRun();
  const run = { controller: new AbortController(), started: Date.now() };
  activeRun = run;
  showState('progress');
  progressFilename.textContent = filename;
  progressStatus.textContent = kind === 'url' ? 'Waiting for server...' : 'Preparing file...';
  cancelBtn.textContent = kind === 'url' ? 'Stop waiting' : 'Cancel';
  document.getElementById('stopExplanation').hidden = kind !== 'url';
  setChunkProgress();
  const elapsed = document.getElementById('progressElapsed');
  const updateElapsed = () => {
    const secs = Math.floor((Date.now() - run.started) / 1000);
    elapsed.textContent = `Elapsed ${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')}`;
  };
  updateElapsed();
  run.timer = setInterval(updateElapsed, 1000);
  return run;
}

// Settle even when an underlying operation (background fetch or audio prep) cannot stop.
function waitForRun(run, promise) {
  const signal = run.controller.signal;
  return new Promise((resolve, reject) => {
    const onAbort = () => reject(new DOMException('Aborted', 'AbortError'));
    if (signal.aborted) onAbort();
    else signal.addEventListener('abort', onAbort, { once: true });
    Promise.resolve(promise).then(value => {
      if (signal.aborted) onAbort();
      else resolve(value);
    }, reject).finally(() => signal.removeEventListener('abort', onAbort));
  });
}

async function pollDelay(run) {
  let timer;
  try {
    await waitForRun(run, new Promise(resolve => { timer = setTimeout(resolve, 3000); }));
  } finally {
    clearTimeout(timer);
  }
}

function setChunkProgress(completed, total) {
  progressRingFill.parentElement.parentElement.classList.toggle('indeterminate', total === undefined);
  progressPct.textContent = total === undefined ? '' : `${completed}/${total}`;
  progressRingFill.style.strokeDashoffset = total ? 2 * Math.PI * 52 * (1 - completed / total) : 0;
}

// URL handling
const URL_PATTERN = /^https?:\/\/([a-z0-9-]+\.)*(tiktok\.com|youtube\.com|youtu\.be|vm\.tiktok\.com|instagram\.com|facebook\.com|fb\.watch|linkedin\.com|licdn\.com|open\.spotify\.com)\/.+/i;
const DIRECT_VIDEO_PATTERN = /^https?:\/\/.+\.(mp4|webm|mov)(\?.*)?$/i;

async function getBackendUrl() {
  const { backendUrl } = await chrome.storage.sync.get('backendUrl');
  return (backendUrl || 'https://api.scribetok.com').replace(/\/$/, '');
}

// Route fetches through background script to bypass CORS preflight
function bgFetch(url, options = {}) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage({ type: 'fetch-proxy', url, options }, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error('Background script unavailable. Try closing and reopening the side panel.'));
        return;
      }
      resolve(response);
    });
  });
}

async function handleUrl(url) {
  if (!URL_PATTERN.test(url) && !DIRECT_VIDEO_PATTERN.test(url)) {
    showError('Enter a valid video or podcast URL.');
    return;
  }

  const run = beginRun('url', url);
  try {
    const backend = await waitForRun(run, getBackendUrl());
    const submitResp = await waitForRun(run, bgFetch(`${backend}/api/public/transcribe`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    }));
    if (!submitResp.ok) {
      throw new Error(`Submit failed (${submitResp.status}): ${submitResp.body || 'Unknown error'}`);
    }
    const submitData = typeof submitResp.body === 'string' ? JSON.parse(submitResp.body) : submitResp.body;
    const task_id = submitData.task_id;
    if (!task_id) throw new Error('No task_id returned from server.');
    progressStatus.textContent = 'Waiting for server status...';

    while (true) {
      await pollDelay(run);
      const taskResp = await waitForRun(run, bgFetch(`${backend}/api/public/tasks/${task_id}`));
      if (!taskResp.ok) continue;
      const task = typeof taskResp.body === 'string' ? JSON.parse(taskResp.body) : taskResp.body;
      if (task.status === 'pending') {
        progressStatus.textContent = 'Queued...';
      } else if (task.status === 'processing') {
        progressStatus.textContent = 'Processing...';
      } else if (task.status === 'failed') {
        throw new Error(task.error || 'Transcription failed on server.');
      } else if (task.status === 'completed') {
        progressStatus.textContent = 'Fetching transcript...';
        const txResp = await waitForRun(run, bgFetch(`${backend}/api/public/transcript/${task_id}?format=plain`));
        if (!txResp.ok) throw new Error('Could not fetch transcript.');
        const transcript = typeof txResp.body === 'string' ? txResp.body : JSON.stringify(txResp.body);
        showState('result');
        resultFilename.textContent = task.title || url;
        showResultHero(task);
        transcriptBox.textContent = transcript;
        urlInput.value = '';
        await waitForRun(run, saveToHistory(task.title || url, transcript, task.thumbnail_url, task, run));
        break;
      } else {
        progressStatus.textContent = 'Waiting for server status...';
      }
    }
  } catch (err) {
    if (activeRun !== run) return;
    showState('input');
    if (err.name !== 'AbortError') showError(err.message);
  } finally {
    if (activeRun === run) stopRun();
  }
}

// File handling
async function handleFile(file) {
  const ext = '.' + file.name.split('.').pop().toLowerCase();
  if (!ACCEPTED_TYPES.includes(ext)) {
    showError('Unsupported format. Use WAV, MP3, MP4, M4A, OGG, or FLAC.');
    return;
  }

  const sizeMB = (file.size / (1024 * 1024)).toFixed(1);
  const run = beginRun('file', `${file.name} — ${sizeMB} MB`);
  try {
    const { openaiApiKey } = await waitForRun(run, chrome.storage.sync.get('openaiApiKey'));
    if (!openaiApiKey) throw new Error('Set your OpenAI API key in Settings.');
    progressStatus.textContent = needsChunking(file) ? 'Splitting audio into chunks...' : 'Preparing file...';
    const chunks = await waitForRun(run, chunkAudioFile(file));
    const totalChunks = chunks.length;
    if (!totalChunks) throw new Error('No audio chunks were prepared.');
    const transcripts = [];
    let partialFailure = false;
    setChunkProgress(0, totalChunks);
    for (let i = 0; i < totalChunks; i++) {
      progressStatus.textContent = `${i} of ${totalChunks} chunks processed. Transcribing chunk ${i + 1}...`;
      try {
        const text = await waitForRun(run, transcribeChunk(chunks[i], openaiApiKey, run.controller.signal));
        transcripts.push(text);
      } catch (chunkErr) {
        if (chunkErr.name === 'AbortError') throw chunkErr;
        partialFailure = true;
        transcripts.push(`[Chunk ${i + 1} failed: ${chunkErr.message}]`);
      }
      setChunkProgress(i + 1, totalChunks);
      progressStatus.textContent = `${i + 1} of ${totalChunks} chunks processed.`;
    }
    const fullText = transcripts.join(' ');
    showState('result');
    resultFilename.textContent = file.name;
    showResultHero(null);
    transcriptBox.textContent = fullText;
    if (partialFailure) {
      warningBanner.textContent = 'Some chunks failed to transcribe. Partial transcript shown.';
      warningBanner.style.display = 'block';
    }
    await waitForRun(run, saveToHistory(file.name, fullText, null, null, run));
  } catch (err) {
    if (activeRun !== run) return;
    showState('input');
    if (err.name !== 'AbortError') showError(err.message);
  } finally {
    if (activeRun === run) stopRun();
  }
}

async function transcribeChunk(chunk, apiKey, signal) {
  const form = new FormData();
  form.append('file', chunk.blob, chunk.name);
  form.append('model', 'whisper-1');

  const resp = await fetch('https://api.openai.com/v1/audio/transcriptions', {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${apiKey}` },
    body: form,
    signal,
  });

  if (!resp.ok) {
    if (resp.status === 401) throw new Error('Invalid API key. Check Settings.');
    if (resp.status === 429) throw new Error('Rate limited. Wait a moment and try again.');
    const body = await resp.text().catch(() => '');
    throw new Error(`API error (${resp.status}): ${body || 'Unknown error'}`);
  }

  const data = await resp.json();
  return data.text;
}

// History
async function saveToHistory(filename, transcript, thumbnailUrl, task, run) {
  const { transcribeHistory = [] } = await chrome.storage.local.get('transcribeHistory');
  if (activeRun !== run) return;
  const entry = {
    metadata: task ? { title: task.title, uploader: task.uploader, channel: task.channel, platform: task.platform, duration: task.duration } : null,
    id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
    filename,
    transcript,
    thumbnailUrl: thumbnailUrl || null,
    date: new Date().toISOString(),
  };
  transcribeHistory.unshift(entry);
  if (transcribeHistory.length > MAX_HISTORY) transcribeHistory.length = MAX_HISTORY;
  await chrome.storage.local.set({ transcribeHistory });
  if (activeRun === run) renderHistory(transcribeHistory);
}

async function loadHistory() {
  const { transcribeHistory = [] } = await chrome.storage.local.get('transcribeHistory');
  renderHistory(transcribeHistory);
}

function renderHistory(history) {
  if (!history.length) {
    historyList.innerHTML = '<li class="history-empty">No transcriptions yet</li>';
    return;
  }
  historyList.innerHTML = '';
  history.forEach((entry) => {
    const li = document.createElement('li');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'history-item';
    button.innerHTML = `
      <span class="history-item-name">${escapeHtml(entry.filename)}</span>
      <span class="history-item-date">${new Date(entry.date).toLocaleDateString()}</span>
    `;
    button.addEventListener('click', () => {
      stopRun();
      showState('result');
      resultFilename.textContent = entry.filename;
      showResultHero({ ...entry.metadata, thumbnail_url: entry.thumbnailUrl, title: entry.filename });
      transcriptBox.textContent = entry.transcript;
    });
    li.appendChild(button);
    historyList.appendChild(li);
  });
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// Init
loadHistory();
