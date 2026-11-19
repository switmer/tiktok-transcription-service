// Offline checks that the extension can load from a clean checkout:
// every file the manifest and pages point at exists, and the MOV helper rules hold.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const manifest = JSON.parse(read('manifest.json'));

test('manifest points at files that exist', () => {
  assert.equal(manifest.manifest_version, 3);
  const files = [
    manifest.side_panel.default_path, manifest.background.service_worker, manifest.options_page,
    ...Object.values(manifest.icons), ...Object.values(manifest.action.default_icon),
  ];
  for (const file of files) assert.ok(fs.existsSync(path.join(root, file)), `missing ${file}`);
});

test('pages load only scripts that exist', () => {
  for (const page of ['sidepanel.html', 'options.html']) {
    for (const [, src] of read(page).matchAll(/<script[^>]+src="([^"]+)"/g)) {
      assert.ok(fs.existsSync(path.join(root, src)), `${page} loads missing ${src}`);
    }
  }
});

test('MOV is converted and other small files pass straight through', async () => {
  const sandbox = {};
  vm.runInNewContext(`${read('audio-utils.js')}\nthis.api = { needsConversion, needsChunking, chunkAudioFile };`, sandbox);
  const { needsConversion, needsChunking, chunkAudioFile } = sandbox.api;
  assert.equal(needsConversion({ name: 'Clip.MOV' }), true);
  assert.equal(needsConversion({ name: 'song.mp3' }), false);
  assert.equal(needsChunking({ size: 26 * 1024 * 1024 }), true);
  const small = { name: 'song.mp3', size: 1024 };
  const chunks = await chunkAudioFile(small);
  assert.equal(chunks.length, 1);
  assert.equal(chunks[0].blob, small);
});
