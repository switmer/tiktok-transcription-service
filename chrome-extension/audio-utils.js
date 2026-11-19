const MAX_SIZE_BYTES = 25 * 1024 * 1024;
const CHUNK_DURATION_SEC = 600; // 10 minutes
const TARGET_SAMPLE_RATE = 16000;

function needsChunking(file) {
  return file.size > MAX_SIZE_BYTES;
}

function needsConversion(file) {
  return file.name.toLowerCase().endsWith('.mov');
}

async function chunkAudioFile(file) {
  // OpenAI does not accept MOV files, so turn their audio into WAV first.
  if (!needsChunking(file) && !needsConversion(file)) {
    return [{ blob: file, name: file.name }];
  }

  const arrayBuffer = await file.arrayBuffer();
  const audioCtx = new OfflineAudioContext(1, 1, TARGET_SAMPLE_RATE);
  let audioBuffer;
  try {
    audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
  } catch (e) {
    throw new Error('Could not read the audio in this file. Try converting it to MP3 first.');
  }

  const totalSamples = audioBuffer.length;
  const sampleRate = audioBuffer.sampleRate;
  const samplesPerChunk = CHUNK_DURATION_SEC * sampleRate;
  const chunks = [];
  let start = 0;
  let i = 0;

  while (start < totalSamples) {
    const end = Math.min(start + samplesPerChunk, totalSamples);
    const wavBlob = encodeWavChunk(audioBuffer, start, end);

    // If WAV chunk exceeds limit, split it further
    if (wavBlob.size > MAX_SIZE_BYTES) {
      const ratio = (MAX_SIZE_BYTES / wavBlob.size) * 0.9;
      const reducedSamples = Math.floor((end - start) * ratio);
      const reducedEnd = start + reducedSamples;
      const smallerBlob = encodeWavChunk(audioBuffer, start, reducedEnd);
      const baseName = file.name.replace(/\.[^.]+$/, '');
      chunks.push({ blob: smallerBlob, name: `${baseName}_chunk${i}.wav` });
      start = reducedEnd;
    } else {
      const baseName = file.name.replace(/\.[^.]+$/, '');
      chunks.push({ blob: wavBlob, name: `${baseName}_chunk${i}.wav` });
      start = end;
    }
    i++;
  }

  return chunks;
}

function encodeWavChunk(audioBuffer, startSample, endSample) {
  const numChannels = 1;
  const sampleRate = audioBuffer.sampleRate;
  const sourceData = audioBuffer.getChannelData(0);
  const segment = sourceData.slice(startSample, endSample);

  // Downsample to 16kHz if needed
  const samples = sampleRate !== TARGET_SAMPLE_RATE
    ? downsample(segment, sampleRate, TARGET_SAMPLE_RATE)
    : segment;

  const numSamples = samples.length;
  const bitsPerSample = 16;
  const byteRate = TARGET_SAMPLE_RATE * numChannels * (bitsPerSample / 8);
  const blockAlign = numChannels * (bitsPerSample / 8);
  const dataSize = numSamples * numChannels * (bitsPerSample / 8);
  const bufferSize = 44 + dataSize;

  const buffer = new ArrayBuffer(bufferSize);
  const view = new DataView(buffer);

  // WAV header
  writeString(view, 0, 'RIFF');
  view.setUint32(4, bufferSize - 8, true);
  writeString(view, 8, 'WAVE');
  writeString(view, 12, 'fmt ');
  view.setUint32(16, 16, true); // chunk size
  view.setUint16(20, 1, true);  // PCM
  view.setUint16(22, numChannels, true);
  view.setUint32(24, TARGET_SAMPLE_RATE, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, bitsPerSample, true);
  writeString(view, 36, 'data');
  view.setUint32(40, dataSize, true);

  // PCM data
  let offset = 44;
  for (let i = 0; i < numSamples; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    const val = clamped < 0 ? clamped * 0x8000 : clamped * 0x7FFF;
    view.setInt16(offset, val, true);
    offset += 2;
  }

  return new Blob([buffer], { type: 'audio/wav' });
}

function downsample(buffer, fromRate, toRate) {
  if (fromRate === toRate) return buffer;
  const ratio = fromRate / toRate;
  const newLength = Math.floor(buffer.length / ratio);
  const result = new Float32Array(newLength);
  for (let i = 0; i < newLength; i++) {
    const srcIndex = i * ratio;
    const low = Math.floor(srcIndex);
    const high = Math.min(low + 1, buffer.length - 1);
    const frac = srcIndex - low;
    result[i] = buffer[low] * (1 - frac) + buffer[high] * frac;
  }
  return result;
}

function writeString(view, offset, string) {
  for (let i = 0; i < string.length; i++) {
    view.setUint8(offset + i, string.charCodeAt(i));
  }
}
