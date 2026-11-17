// Mocked rendered panel tests: no extension runtime, server, secrets, or network.
// PLAYWRIGHT_PATH=/path/to/node_modules/playwright node chrome-extension/tests/sidepanel.rendered.cjs
// PANEL_SOURCE_DIR=/tmp/old-panel exercises the same tests against baseline files.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_PATH || 'playwright');
const source = process.env.PANEL_SOURCE_DIR || path.resolve(__dirname, '..');
const artifacts = process.env.PANEL_ARTIFACTS || '/tmp/extension-ui-qa/screenshots';
let browser;
before(async () => { browser = await chromium.launch({ headless: true }); fs.mkdirSync(artifacts, { recursive: true }); });
after(async () => { await browser?.close(); });

async function panel(t, history = []) {
  const context = await browser.newContext({ viewport: { width: 320, height: 740 }, reducedMotion: 'reduce' });
  t.after(() => context.close());
  const page = await context.newPage();
  page.setDefaultTimeout(1500);
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  t.after(() => assert.deepEqual(errors, [], 'no unhandled script errors'));
  await page.route('**/*', route => {
    const name = new URL(route.request().url()).pathname.slice(1);
    if (['sidepanel.html', 'sidepanel.js'].includes(name)) {
      return route.fulfill({ contentType: name.endsWith('html') ? 'text/html' : 'text/javascript', body: fs.readFileSync(path.join(source, name), 'utf8') });
    }
    if (name === 'audio-utils.js') return route.fulfill({ contentType: 'text/javascript', body: '' });
    return route.abort(); // All unrecognized requests blocked, including thumbnails.
  });
  await page.addInitScript(({ history }) => {
    window.mock = {
      history, requests: [], chunks: [], settings: 0, settled: [], holdSettings: false, settingsWaits: [],
      reply(kind, body, ok = true) {
        const index = this.requests.findIndex(r => r.kind === kind);
        if (index < 0) throw Error(`No pending ${kind}`);
        this.requests.splice(index, 1)[0].callback({ ok, status: ok ? 200 : 500, body });
      },
    };
    window.chrome = {
      runtime: {
        openOptionsPage() { mock.settings++; },
        sendMessage({ url }, callback) {
          mock.requests.push({ kind: url.includes('/tasks/') ? 'poll' : url.includes('/transcript/') ? 'transcript' : 'submit', callback });
        },
      },
      storage: {
        sync: { get: () => mock.holdSettings ? new Promise(resolve => mock.settingsWaits.push(resolve)) : Promise.resolve({ backendUrl: 'https://backend.invalid', openaiApiKey: 'mock-key' }) },
        local: {
          get: async () => ({ transcribeHistory: structuredClone(mock.history) }),
          set: async ({ transcribeHistory }) => { mock.history = structuredClone(transcribeHistory); },
        },
      },
    };
    window.needsChunking = () => false;
    window.chunkAudioFile = () => new Promise((resolve, reject) => { mock.prep = { resolve, reject }; });
    window.fetch = (_url, options) => new Promise((resolve, reject) => {
      mock.chunks.push({ resolve: text => resolve({ ok: true, json: async () => ({ text }) }), reject, signal: options.signal });
    });
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: async text => { mock.clipboard = text; } } });
    HTMLAnchorElement.prototype.click = function () { mock.download = this.download; };
  }, { history });
  await page.goto('https://panel.invalid/sidepanel.html');
  await page.clock.install();
  await page.evaluate(() => {
    window.startUrl = name => {
      const pending = handleUrl(`https://youtube.com/watch?v=${name}`);
      pending.then(() => mock.settled.push(name));
    };
    window.startFile = name => {
      const pending = handleFile(new File(['audio'], name));
      pending.then(() => mock.settled.push(name));
    };
  });
  return page;
}
const text = (page, id) => page.locator(`#${id}`).textContent();
const tick = async page => { await page.clock.runFor(3001); };
async function reply(page, kind, body, ok = true) { await page.evaluate(({ kind, body, ok }) => mock.reply(kind, body, ok), { kind, body, ok }); }
async function screenshot(page, name) {
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, 'fits 320px panel');
  await page.screenshot({ path: path.join(artifacts, `${name}.png`), fullPage: true });
}
const entry = (filename, thumbnailUrl = null) => ({ filename, thumbnailUrl, transcript: `Text for ${filename}`, date: '2026-01-01', metadata: { platform: 'youtube', uploader: 'A channel', duration: 65 } });

test('input keyboard, visible URL label, live errors and 320px layout', async t => {
  const page = await panel(t);
  await page.locator('#openSettings').focus();
  await page.keyboard.press('Enter');
  assert.equal(await page.evaluate(() => mock.settings), 1);
  assert.equal(await page.locator('#openSettings').evaluate(el => getComputedStyle(el).outlineStyle), 'solid');
  assert.equal(await page.locator('label[for=urlInput]').isVisible(), true);
  await screenshot(page, 'input');
  await page.locator('#urlInput').fill('invalid');
  await page.locator('#urlInput').press('Enter');
  assert.equal(await page.locator('#errorMsg').getAttribute('role'), 'alert');
  assert.match(await text(page, 'errorMsg'), /valid video/);
  await screenshot(page, 'error');
});

test('URL waiting, queued, processing, no made-up percentages, result metadata and history', async t => {
  const page = await panel(t);
  await page.evaluate(() => startUrl('one'));
  assert.equal(await text(page, 'cancelBtn'), 'Stop waiting');
  assert.match(await text(page, 'stopExplanation'), /server task continues/);
  assert.equal(await text(page, 'progressPct'), '');
  assert.equal(await page.locator('#progressStatus').getAttribute('aria-live'), 'polite');
  assert.equal(await page.locator('#progressRingFill').evaluate(el => getComputedStyle(el).animationName), 'none');
  await reply(page, 'submit', { task_id: 'one' });
  await tick(page); await reply(page, 'poll', { status: 'pending' });
  assert.equal(await text(page, 'progressStatus'), 'Queued...');
  assert.match(await text(page, 'progressElapsed'), /0:03/);
  await screenshot(page, 'progress');
  await tick(page); await reply(page, 'poll', { status: 'processing' });
  assert.equal(await text(page, 'progressStatus'), 'Processing...');
  await tick(page); await reply(page, 'poll', { status: 'completed', title: 'A video without a thumbnail', platform: 'youtube', uploader: 'A channel', duration: 65 });
  await reply(page, 'transcript', 'The transcript');
  assert.equal(await page.locator('#resultTitle').isVisible(), true);
  assert.equal(await text(page, 'resultTitle'), 'A video without a thumbnail');
  assert.equal(await text(page, 'resultDuration'), '1:05');
  await screenshot(page, 'result');
  await page.locator('#copyBtn').click();
  assert.equal(await page.evaluate(() => mock.clipboard), 'The transcript');
  await page.locator('#newBtn').click();
  await screenshot(page, 'history');
  await page.locator('.history-item').focus(); await page.keyboard.press('Enter');
  assert.equal(await text(page, 'resultChannel'), 'A channel');
  await page.locator('#downloadBtn').click();
  assert.equal(await page.evaluate(() => mock.download), 'A video without a thumbnail.txt');
});

for (const stage of ['settings', 'submit', 'delay', 'poll', 'transcript']) {
  test(`URL stop settles at ${stage}; late old reply cannot overwrite or cancel new run`, async t => {
    const page = await panel(t);
    if (stage === 'settings') await page.evaluate(() => { mock.holdSettings = true; });
    await page.evaluate(() => startUrl('old'));
    if (['delay', 'poll', 'transcript'].includes(stage)) await reply(page, 'submit', { task_id: 'old' });
    if (['poll', 'transcript'].includes(stage)) await tick(page);
    if (stage === 'transcript') await reply(page, 'poll', { status: 'completed', title: 'OLD' });
    await page.locator('#cancelBtn').click();
    assert.equal(await page.evaluate(() => mock.settled.includes('old')), true, 'stopped promise settles immediately');
    await page.evaluate(() => { mock.holdSettings = false; startUrl('new'); });
    if (stage === 'settings') await page.evaluate(() => mock.settingsWaits[0]({ backendUrl: 'https://backend.invalid' }));
    if (stage === 'submit') await reply(page, 'submit', { task_id: 'old' });
    if (stage === 'poll') await reply(page, 'poll', { status: 'failed', error: 'OLD failure' });
    if (stage === 'transcript') await reply(page, 'transcript', 'OLD transcript');
    assert.equal(await page.locator('#progressSection').isVisible(), true);
    assert.match(await text(page, 'progressFilename'), /new/);
    assert.equal(await page.locator('#errorMsg').isVisible(), false);
    await reply(page, 'submit', { task_id: 'new' });
    await tick(page); await reply(page, 'poll', { status: 'failed', error: 'New failure' });
    assert.equal(await text(page, 'errorMsg'), 'New failure');
    assert.deepEqual(await page.evaluate(() => mock.settled), ['old', 'new']);
    assert.equal(await page.evaluate(() => mock.history.length), 0);
  });
}

test('file prep spinner, measured processed chunks, partial failure and file title', async t => {
  const page = await panel(t);
  await page.evaluate(() => startFile('voice.mp3'));
  assert.equal(await text(page, 'progressPct'), '');
  assert.equal(await text(page, 'cancelBtn'), 'Cancel');
  await page.evaluate(() => mock.prep.resolve([1, 2, 3].map(i => ({ blob: new Blob(['audio']), name: `${i}.wav` }))));
  assert.equal(await text(page, 'progressPct'), '0/3');
  await page.evaluate(() => mock.chunks[0].resolve('First chunk'));
  assert.equal(await text(page, 'progressPct'), '1/3');
  assert.match(await text(page, 'progressStatus'), /1 of 3 chunks processed/);
  await page.evaluate(() => mock.chunks[1].reject(new Error('Mock failure')));
  assert.equal(await text(page, 'progressPct'), '2/3');
  assert.match(await text(page, 'progressStatus'), /2 of 3 chunks processed/);
  await page.evaluate(() => mock.chunks[2].resolve('Last chunk'));
  assert.equal(await text(page, 'resultTitle'), 'voice.mp3');
  assert.equal(await page.locator('#resultTitle').isVisible(), true);
  assert.equal(await page.locator('#warningBanner').isVisible(), true);
  assert.match(await text(page, 'transcriptBox'), /First chunk.*Mock failure/);
});

for (const stage of ['settings', 'prep', 'chunk']) {
  test(`file cancel at ${stage} settles and cannot overwrite new run`, async t => {
    const page = await panel(t);
    if (stage === 'settings') await page.evaluate(() => { mock.holdSettings = true; });
    await page.evaluate(() => startFile('old.mp3'));
    if (stage === 'chunk') await page.evaluate(() => mock.prep.resolve([{ blob: new Blob(['a']), name: 'a.wav' }]));
    await page.locator('#cancelBtn').click();
    assert.equal(await page.evaluate(() => mock.settled.includes('old.mp3')), true);
    if (stage === 'chunk') assert.equal(await page.evaluate(() => mock.chunks[0].signal.aborted), true);
    await page.evaluate(() => { mock.holdSettings = false; startUrl('new'); });
    if (stage === 'settings') await page.evaluate(() => mock.settingsWaits[0]({ openaiApiKey: 'mock' }));
    if (stage === 'prep') await page.evaluate(() => mock.prep.reject(new Error('Old prep failure')));
    if (stage === 'chunk') await page.evaluate(() => mock.chunks[0].resolve('Old text'));
    assert.match(await text(page, 'progressFilename'), /new/);
    assert.equal(await page.locator('#errorMsg').isVisible(), false);
    await page.locator('#cancelBtn').click();
    assert.equal(await page.evaluate(() => mock.history.length), 0);
  });
}

test('keyboard history stops current wait and preserves title for present, absent, broken thumbnails', async t => {
  const page = await panel(t, [entry('no-thumb.mp3'), entry('broken title', 'https://images.invalid/broken.png'), entry('with thumbnail', 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="16" height="9"><rect width="16" height="9" fill="blue"/></svg>')]);
  for (let i = 0; i < 3; i++) {
    await page.evaluate(() => startUrl('waiting'));
    await page.locator('.history-item').nth(i).focus(); await page.keyboard.press('Space');
    assert.equal(await page.locator('#resultTitle').isVisible(), true);
    assert.equal(await text(page, 'resultTitle'), ['no-thumb.mp3', 'broken title', 'with thumbnail'][i]);
    await reply(page, 'submit', { task_id: 'late' });
    await page.locator('#downloadBtn').click();
    assert.equal(await page.evaluate(() => mock.download), ['no-thumb.txt', 'broken title.txt', 'with thumbnail.txt'][i]);
  }
  assert.deepEqual(await page.evaluate(() => mock.settled), ['waiting', 'waiting', 'waiting']);
});

test('server submission and transcript errors return to input', async t => {
  const page = await panel(t);
  await page.evaluate(() => startUrl('bad-submit'));
  await reply(page, 'submit', 'Mock submit failure', false);
  assert.match(await text(page, 'errorMsg'), /Submit failed/);
  await page.evaluate(() => startUrl('bad-transcript'));
  await reply(page, 'submit', { task_id: 'bad' }); await tick(page);
  await reply(page, 'poll', { status: 'completed' });
  await reply(page, 'transcript', 'Mock failure', false);
  assert.equal(await text(page, 'errorMsg'), 'Could not fetch transcript.');
  assert.equal(await page.locator('#urlSection').isVisible(), true);
  assert.equal(await page.evaluate(() => mock.history.length), 0);
});

test('slow URL polling stays sequential and Stop waiting prevents later polling', async t => {
  const page = await panel(t);
  await page.evaluate(() => startUrl('slow'));
  await reply(page, 'submit', { task_id: 'slow' });
  await page.clock.runFor(12001);
  assert.equal(await page.evaluate(() => mock.requests.filter(r => r.kind === 'poll').length), 1);
  await page.locator('#cancelBtn').click();
  await reply(page, 'poll', { status: 'processing' });
  await page.clock.runFor(12001);
  assert.equal(await page.evaluate(() => mock.requests.length), 0);
  assert.equal(await page.evaluate(() => mock.settled.includes('slow')), true);
});

test('file prep error and missing key return to input without a stale result', async t => {
  const page = await panel(t);
  await page.evaluate(() => startFile('bad.mp3'));
  await page.evaluate(() => mock.prep.reject(new Error('Cannot decode audio')));
  assert.equal(await text(page, 'errorMsg'), 'Cannot decode audio');
  await page.evaluate(() => { chrome.storage.sync.get = async () => ({}); startFile('no-key.mp3'); });
  assert.match(await text(page, 'errorMsg'), /API key in Settings/);
  assert.equal(await page.locator('#dropZone').isVisible(), true);
  assert.equal(await page.evaluate(() => mock.history.length), 0);
});


test('source URL survives saving, reopening history, copying and downloading', async t => {
  const page = await panel(t);
  await page.evaluate(() => startUrl('source'));
  await reply(page, 'submit', { task_id: 'source' });
  await tick(page);
  await reply(page, 'poll', { status: 'completed', title: 'Source title' });
  await reply(page, 'transcript', 'Saved transcript');
  assert.equal(await page.locator('#sourceLink').getAttribute('href'), 'https://youtube.com/watch?v=source');
  await page.locator('#copySourceBtn').click();
  assert.equal(await page.evaluate(() => mock.clipboard), 'https://youtube.com/watch?v=source');
  assert.equal(await page.evaluate(() => mock.history[0].sourceUrl), 'https://youtube.com/watch?v=source');
  await page.locator('#newBtn').click();
  await page.locator('.history-item').click();
  assert.equal(await page.locator('#sourceLink').isVisible(), true);
  await page.locator('#copyBtn').click();
  assert.equal(await page.evaluate(() => mock.clipboard), 'Saved transcript');
  await page.locator('#downloadBtn').click();
  assert.equal(await page.evaluate(() => mock.download), 'Source title.txt');
  await screenshot(page, 'source-link');
});

test('older history recovers YouTube source from its stored thumbnail', async t => {
  const page = await panel(t, [entry('Old video', 'https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg')]);
  await page.locator('.history-item').click();
  assert.equal(await page.locator('#sourceLink').getAttribute('href'), 'https://www.youtube.com/watch?v=abcdefghijk');
  assert.match(await text(page, 'sourceNote'), /Recovered/);
  assert.equal(await page.evaluate(() => mock.history[0].sourceUrl), undefined, 'opening history does not rewrite it');
});

test('old entries without recoverable URLs say so and unsafe URLs never become links', async t => {
  const items = [entry('No saved source'), { ...entry('Unsafe', 'https://evil.invalid/vi/abcdefghijk/hqdefault.jpg'), sourceUrl: 'javascript:alert(1)' }, { ...entry('URL filename'), filename: 'https://youtube.com/watch?v=legacy' }];
  const page = await panel(t, items);
  await page.locator('.history-item').nth(2).click();
  assert.equal(await page.locator('#sourceLink').getAttribute('href'), 'https://youtube.com/watch?v=legacy');
  await page.locator('.history-item').nth(0).click();
  assert.equal(await page.locator('#sourceLink').isVisible(), false);
  assert.match(await text(page, 'sourceNote'), /wasn.t saved/);
  await page.locator('.history-item').nth(1).click();
  assert.equal(await page.locator('#copySourceBtn').isVisible(), false);
  assert.equal(await page.locator('#sourceLink').getAttribute('href'), null);
});

test('local-file result clears prior source link and clipboard failures are announced', async t => {
  const page = await panel(t, [{ ...entry('Video'), sourceUrl: 'https://youtube.com/watch?v=saved' }]);
  await page.locator('.history-item').click();
  await page.evaluate(() => { navigator.clipboard.writeText = async () => { throw Error('denied'); }; });
  await page.locator('#copySourceBtn').click();
  assert.equal(await text(page, 'sourceNote'), 'Could not copy link. Select the URL to copy it.');
  await page.evaluate(() => startFile('voice.mp3'));
  await page.evaluate(() => mock.prep.resolve([{ blob: new Blob(['audio']), name: 'voice.wav' }]));
  await page.evaluate(() => mock.chunks[0].resolve('File transcript'));
  assert.equal(await page.locator('#sourceLink').isVisible(), false);
  assert.equal(await page.locator('#sourceLink').getAttribute('href'), null);
  assert.equal(await text(page, 'sourceNote'), 'Local file');
});
