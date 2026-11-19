const apiKeyInput = document.getElementById('apiKey');
const backendUrlInput = document.getElementById('backendUrl');
const saveBtn = document.getElementById('saveBtn');
const status = document.getElementById('status');

// Load saved settings
chrome.storage.sync.get(['openaiApiKey', 'backendUrl'], ({ openaiApiKey, backendUrl }) => {
  if (openaiApiKey) apiKeyInput.value = openaiApiKey;
  backendUrlInput.value = backendUrl || 'https://api.scribetok.com';
});

saveBtn.addEventListener('click', () => {
  const key = apiKeyInput.value.trim();
  const url = backendUrlInput.value.trim() || 'https://api.scribetok.com';
  chrome.storage.sync.set({ openaiApiKey: key, backendUrl: url }, () => {
    status.style.display = 'block';
    setTimeout(() => { status.style.display = 'none'; }, 2000);
  });
});
