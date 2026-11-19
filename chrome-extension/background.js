chrome.action.onClicked.addListener((tab) => {
  chrome.sidePanel.open({ windowId: tab.windowId });
});

// Proxy fetch requests from sidepanel to bypass CORS preflight
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type !== 'fetch-proxy') return false;
  (async () => {
    try {
      const resp = await fetch(msg.url, msg.options || {});
      const contentType = resp.headers.get('content-type') || '';
      const body = contentType.includes('application/json')
        ? await resp.json()
        : await resp.text();
      sendResponse({ ok: resp.ok, status: resp.status, body });
    } catch (err) {
      sendResponse({ ok: false, status: 0, body: err.message });
    }
  })();
  return true; // keep message channel open for async response
});
