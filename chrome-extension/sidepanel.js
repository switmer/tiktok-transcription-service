const ACCEPTED_TYPES = ['.wav', '.mp3', '.mp4', '.m4a', '.ogg', '.flac'];
const MAX_HISTORY = 20;

let abortController = null;
let elapsedTimer = null;
let elapsedSeconds = 0;
let fakeProgressTimer = null;
let fakeProgress = 0;
let pollTimer = null;

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

// Cancel — snap back to input immediately
cancelBtn.addEventListener('click', () => {
  if (abortController) abortController.abort();
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  stopElapsedTimer();
  stopFakeProgress();
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

  if (thumb) {
    resultHeroImg.src = thumb;
    resultHero.classList.remove('result-hero-hidden');
  } else {
    resultHero.classList.add('result-hero-hidden');
  }

  resultTitle.textContent = title || '';
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

// Elapsed timer
function formatElapsed(secs) {
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function startElapsedTimer() {
  stopElapsedTimer();
  elapsedSeconds = 0;
  elapsedTimer = setInterval(() => {
    elapsedSeconds++;
    const statusEl = document.getElementById('progressStatus');
    const base = statusEl.textContent.replace(/ \(\d+:\d{2}\)$/, '');
    statusEl.textContent = `${base} (${formatElapsed(elapsedSeconds)})`;
  }, 1000);
}

function stopElapsedTimer() {
  if (elapsedTimer) {
    clearInterval(elapsedTimer);
    elapsedTimer = null;
  }
}

// Ring progress helpers
const RING_CIRCUMFERENCE = 2 * Math.PI * 52; // ~326.73

function setRingProgress(pct) {
  const offset = RING_CIRCUMFERENCE * (1 - pct / 100);
  progressRingFill.style.strokeDashoffset = offset;
  progressPct.textContent = `${Math.round(pct)}%`;
}

// Fake progress — decelerating crawl toward a ceiling, never quite reaching it
function startFakeProgress(ceiling = 90) {
  stopFakeProgress();
  setRingProgress(fakeProgress);
  fakeProgressTimer = setInterval(() => {
    const remaining = ceiling - fakeProgress;
    const step = remaining * (0.02 + Math.random() * 0.04);
    fakeProgress = Math.min(fakeProgress + step, ceiling);
    setRingProgress(fakeProgress);
  }, 300);
}

function jumpFakeProgress(minPct) {
  if (fakeProgress < minPct) {
    fakeProgress = minPct;
    setRingProgress(fakeProgress);
  }
}

function finishFakeProgress() {
  stopFakeProgress();
  fakeProgress = 100;
  setRingProgress(100);
}

function stopFakeProgress() {
  if (fakeProgressTimer) {
    clearInterval(fakeProgressTimer);
    fakeProgressTimer = null;
  }
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

  const backend = await getBackendUrl();

  showState('progress');
  progressFilename.textContent = url;
  progressStatus.textContent = 'Submitting...';
  startElapsedTimer();
  fakeProgress = 0;
  setRingProgress(0);
  startFakeProgress(30);

  abortController = new AbortController();

  try {
    // Submit URL to backend (via background script to bypass CORS)
    const submitResp = await bgFetch(`${backend}/api/public/transcribe`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });

    if (!submitResp.ok) {
      throw new Error(`Submit failed (${submitResp.status}): ${submitResp.body || 'Unknown error'}`);
    }

    const submitData = typeof submitResp.body === 'string' ? JSON.parse(submitResp.body) : submitResp.body;
    const task_id = submitData.task_id;
    if (!task_id) throw new Error('No task_id returned from server.');

    // Poll for completion
    stopFakeProgress();
    jumpFakeProgress(10);
    startFakeProgress(70);
    progressStatus.textContent = 'Downloading...';

    await new Promise((resolve, reject) => {
      pollTimer = setInterval(async () => {
        if (abortController && abortController.signal.aborted) {
          clearInterval(pollTimer);
          pollTimer = null;
          reject(new DOMException('Aborted', 'AbortError'));
          return;
        }
        try {
          const taskResp = await bgFetch(`${backend}/api/public/tasks/${task_id}`);
          if (!taskResp.ok) return; // retry next tick
          const task = typeof taskResp.body === 'string' ? JSON.parse(taskResp.body) : taskResp.body;

          if (task.status === 'downloading') {
            progressStatus.textContent = 'Downloading...';
            jumpFakeProgress(15);
          } else if (task.status === 'transcribing') {
            progressStatus.textContent = 'Transcribing...';
            stopFakeProgress();
            jumpFakeProgress(35);
            startFakeProgress(80);
          } else if (task.status === 'completed') {
            clearInterval(pollTimer);
            pollTimer = null;
            finishFakeProgress();
            stopElapsedTimer();

            // Fetch transcript
            const txResp = await bgFetch(`${backend}/api/public/transcript/${task_id}?format=plain`);
            const transcript = txResp.ok ? (typeof txResp.body === 'string' ? txResp.body : JSON.stringify(txResp.body)) : '[Could not fetch transcript]';

            showState('result');
            showResultHero(task);
            resultFilename.textContent = task.title || url;
            transcriptBox.textContent = transcript;
            urlInput.value = '';

            await saveToHistory(task.title || url, transcript, task.thumbnail_url);
            resolve();
          } else if (task.status === 'failed') {
            clearInterval(pollTimer);
            pollTimer = null;
            reject(new Error(task.error || 'Transcription failed on server.'));
          }
        } catch (err) {
          clearInterval(pollTimer);
          pollTimer = null;
          reject(err);
        }
      }, 3000);
    });

  } catch (err) {
    stopFakeProgress();
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    if (err.name === 'AbortError') {
      stopElapsedTimer();
      showState('input');
      return;
    }
    stopElapsedTimer();
    showState('input');
    showError(err.message);
  } finally {
    abortController = null;
  }
}

// File handling
async function handleFile(file) {
  const ext = '.' + file.name.split('.').pop().toLowerCase();
  if (!ACCEPTED_TYPES.includes(ext)) {
    showError('Unsupported format. Use WAV, MP3, MP4, M4A, OGG, or FLAC.');
    return;
  }

  // Check API key
  const { openaiApiKey } = await chrome.storage.sync.get('openaiApiKey');
  if (!openaiApiKey) {
    showError('Set your OpenAI API key in Settings.');
    return;
  }

  showState('progress');
  const sizeMB = (file.size / (1024 * 1024)).toFixed(1);
  progressFilename.textContent = `${file.name} \u2014 ${sizeMB} MB`;
  progressStatus.textContent = 'Preparing...';
  startElapsedTimer();
  fakeProgress = 0;
  setRingProgress(0);
  startFakeProgress(15); // crawl to ~15% during prep

  abortController = new AbortController();

  try {
    // Chunk the audio
    progressStatus.textContent = needsChunking(file)
      ? 'Splitting audio into chunks...'
      : 'Preparing file...';

    const chunks = await chunkAudioFile(file);
    const totalChunks = chunks.length;
    const transcripts = [];
    let partialFailure = false;

    // Prep done — now crawl toward 90% during transcription
    stopFakeProgress();
    jumpFakeProgress(15);
    startFakeProgress(90);

    for (let i = 0; i < totalChunks; i++) {
      if (abortController.signal.aborted) throw new DOMException('Aborted', 'AbortError');

      progressStatus.textContent = totalChunks > 1
        ? `Transcribing chunk ${i + 1} of ${totalChunks}...`
        : 'Transcribing...';

      try {
        const text = await transcribeChunk(chunks[i], openaiApiKey, abortController.signal);
        transcripts.push(text);
      } catch (chunkErr) {
        if (chunkErr.name === 'AbortError') throw chunkErr;
        partialFailure = true;
        transcripts.push(`[Chunk ${i + 1} failed: ${chunkErr.message}]`);
      }
      // Ensure bar is at least at the real chunk progress (15-90% range)
      jumpFakeProgress(15 + ((i + 1) / totalChunks) * 75);
    }

    finishFakeProgress();
    stopElapsedTimer();
    const fullText = transcripts.join(' ');

    // Show result
    showState('result');
    showResultHero(null);
    resultFilename.textContent = file.name;
    resultFilename.style.display = 'block';
    transcriptBox.textContent = fullText;

    if (partialFailure) {
      warningBanner.textContent = 'Some chunks failed to transcribe. Partial transcript shown.';
      warningBanner.style.display = 'block';
    }

    // Save to history
    await saveToHistory(file.name, fullText);

  } catch (err) {
    stopFakeProgress();
    if (err.name === 'AbortError') {
      stopElapsedTimer();
      showState('input');
      return;
    }
    stopElapsedTimer();
    showState('input');
    showError(err.message);
  } finally {
    abortController = null;
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
async function saveToHistory(filename, transcript, thumbnailUrl) {
  const { transcribeHistory = [] } = await chrome.storage.local.get('transcribeHistory');
  const entry = {
    id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
    filename,
    transcript,
    thumbnailUrl: thumbnailUrl || null,
    date: new Date().toISOString(),
  };
  transcribeHistory.unshift(entry);
  if (transcribeHistory.length > MAX_HISTORY) transcribeHistory.length = MAX_HISTORY;
  await chrome.storage.local.set({ transcribeHistory });
  renderHistory(transcribeHistory);
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
    li.className = 'history-item';
    li.innerHTML = `
      <span class="history-item-name">${escapeHtml(entry.filename)}</span>
      <span class="history-item-date">${new Date(entry.date).toLocaleDateString()}</span>
    `;
    li.addEventListener('click', () => {
      showState('result');
      showResultHero(entry.thumbnailUrl ? { thumbnail_url: entry.thumbnailUrl, title: entry.filename } : null);
      if (!entry.thumbnailUrl) {
        resultFilename.textContent = entry.filename;
        resultFilename.style.display = 'block';
      }
      transcriptBox.textContent = entry.transcript;
    });
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
