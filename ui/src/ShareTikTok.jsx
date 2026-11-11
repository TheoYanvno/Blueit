import { useState } from 'react';
import { tiktokCaption } from './caption.js';

// TikTok only lets audited apps post publicly through its API, so Blueit prepares the post for you:
// download the part, copy a caption that credits the writer, then upload it on TikTok yourself.
export default function ShareTikTok({ story, videos, current, mediaUrl }) {
  const [video, setVideo] = useState(current || videos[0]);
  const [note, setNote] = useState('');
  const caption = tiktokCaption(story, video);

  async function copy() {
    try {
      await navigator.clipboard.writeText(caption);
      setNote('Caption copied.');
    } catch {
      setNote("Your browser didn't allow copying; select the caption and copy it.");
    }
  }

  return (
    <section className="share" aria-labelledby="tt-title">
      <h3 id="tt-title">Post to TikTok</h3>
      <ol className="steps">
        <li>
          <label>Video
            <select value={video} onChange={e => setVideo(e.target.value)}>
              {videos.map(v => <option key={v} value={v}>{v === 'full.mp4' ? 'Full video' : v.replace('part-', 'Part ').replace('.mp4', '')}</option>)}
            </select>
          </label>
          <a className="button" href={mediaUrl(video)} download>Download it</a>
        </li>
        <li>
          <label className="caption">Caption
            <textarea readOnly value={caption} rows={4} />
          </label>
          <button onClick={copy}>Copy caption</button> <span className="muted small" role="status">{note}</span>
        </li>
        <li>
          <a className="button primary" href="https://www.tiktok.com/upload" target="_blank" rel="noreferrer noopener">Open TikTok upload</a>
          <span className="muted small"> Choose the downloaded file, paste the caption and post.</span>
        </li>
      </ol>
      <p className="muted small">Parts are at most a minute and upright, which TikTok plays full screen. Only post stories you have permission to use.</p>
    </section>
  );
}
