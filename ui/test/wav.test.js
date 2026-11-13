import { test } from 'node:test';
import assert from 'node:assert/strict';
import { encodeWav, mixDown, clock } from '../src/wav.js';

test('encodeWav writes a 16-bit mono WAV header and clipped samples', () => {
  const buf = encodeWav(new Float32Array([0, 0.5, -1, 2]), 24000);
  const v = new DataView(buf);
  const str = (at, n) => String.fromCharCode(...new Uint8Array(buf, at, n));
  assert.equal(str(0, 4), 'RIFF');
  assert.equal(str(8, 4), 'WAVE');
  assert.equal(v.getUint16(22, true), 1, 'mono');
  assert.equal(v.getUint32(24, true), 24000);
  assert.equal(v.getUint16(34, true), 16);
  assert.equal(v.getUint32(40, true), 8);
  assert.deepEqual([0, 1, 2, 3].map((i) => v.getInt16(44 + i * 2, true)), [0, 16383, -32768, 32767]);
});

test('mixDown averages the channels', () => {
  const buf = { numberOfChannels: 2, length: 2, getChannelData: (c) => (c ? new Float32Array([1, 0]) : new Float32Array([0, 0])) };
  assert.deepEqual([...mixDown(buf)], [0.5, 0]);
});

test('clock shows minutes and seconds', () => {
  assert.equal(clock(0), '0:00');
  assert.equal(clock(305.4), '5:05');
});
