import { test } from 'node:test';
import assert from 'node:assert/strict';
import { tiktokCaption } from '../src/caption.js';

const story = { title: 'The Visitor', author: 'writer_one', subreddit: 'Glitch_in_the_Matrix' };

test('a caption credits the writer and names the part', () => {
  const c = tiktokCaption(story, 'part-02.mp4');
  assert.match(c, /^The Visitor \(Part 2\)\n/);
  assert.match(c, /Written by u\/writer_one on r\/Glitch_in_the_Matrix\./);
  assert.match(c, /#GlitchintheMatrix$/);
  assert.doesNotMatch(tiktokCaption(story, 'full.mp4'), /Part/);
});

test('captions stay within TikTok\'s 2,200 characters', () => {
  assert.equal(tiktokCaption({ ...story, title: 'x'.repeat(5000) }, 'full.mp4').length, 2200);
});
