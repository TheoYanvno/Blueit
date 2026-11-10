import { useEffect, useState } from 'react';
import { api, get } from './api.js';

// Share a made video to YouTube: connect once with your own Google project, pick the video and who
// can see it, then upload. New uploads are private unless you choose otherwise.
export default function ShareYouTube({ storyId, videos, current }) {
  const [status, setStatus] = useState(null);
  const [video, setVideo] = useState(current || videos[0]);
  const [privacy, setPrivacy] = useState('private');
  const [error, setError] = useState('');

  useEffect(() => { if (current) setVideo(current); }, [current]);

  useEffect(() => {
    let alive = true, timer;
    async function poll() {
      try {
        const s = await get('/api/youtube');
        if (!alive) return;
        setStatus(s);
        if (s.share.state === 'running' || !s.connected) timer = setTimeout(poll, s.connected ? 1500 : 4000);
      } catch (e) { if (alive) setError(e.message); }
    }
    poll();
    return () => { alive = false; clearTimeout(timer); };
  }, [storyId]);

  async function connect() {
    setError('');
    try {
      const { url } = await api('/api/youtube/connect', {});
      window.open(url, '_blank', 'noopener');
    } catch (e) { setError(e.message); }
  }

  async function share() {
    setError('');
    try {
      const share = await api('/api/share/youtube', { id: storyId, video, privacy });
      setStatus(s => ({ ...s, share }));
      const tick = async () => {
        const s = await get('/api/youtube');
        setStatus(s);
        if (s.share.state === 'running') setTimeout(tick, 1500);
      };
      setTimeout(tick, 1500);
    } catch (e) { setError(e.message); }
  }

  if (!status) return null;
  const sh = status.share.id === storyId ? status.share : { state: 'idle' };
  const pct = sh.total ? Math.round((sh.done / sh.total) * 100) : 0;
  return (
    <section className="share" aria-labelledby="share-title">
      <h3 id="share-title">Share to YouTube</h3>
      {!status.ready ? (
        <p className="muted small">To upload from here, add your own Google client file as <code>youtube_client.json</code> in your Blueit folder. The README's “Sharing to YouTube” section walks through it.</p>
      ) : !status.connected ? (
        <div className="row"><button onClick={connect}>Connect YouTube</button><span className="muted small">Opens Google's sign-in in a new tab. Come back here when it says connected.</span></div>
      ) : (
        <>
          <div className="row">
            <label>Video
              <select value={video} onChange={e => setVideo(e.target.value)}>
                {videos.map(v => <option key={v} value={v}>{v === 'full.mp4' ? 'Full video' : v.replace('part-', 'Part ').replace('.mp4', '')}</option>)}
              </select>
            </label>
            <label>Who can see it
              <select value={privacy} onChange={e => setPrivacy(e.target.value)}>
                <option value="private">Private (only you)</option>
                <option value="unlisted">Unlisted (anyone with the link)</option>
                <option value="public">Public</option>
              </select>
            </label>
            <button className="primary" disabled={sh.state === 'running'} onClick={share}>Upload to YouTube</button>
          </div>
          <p className="muted small">Credit goes to the writer in the description. Only share stories you have permission to use.</p>
        </>
      )}
      {sh.state === 'running' && <p role="status">Uploading {sh.title}… {pct}% <progress max="100" value={pct} /></p>}
      {sh.state === 'done' && <p className="ok" role="status">✓ Uploaded: <a href={sh.link} target="_blank" rel="noreferrer noopener">{sh.link}</a></p>}
      {sh.state === 'error' && <p className="error" role="alert">Upload failed: {sh.error}</p>}
      {error && <p className="error" role="alert">{error}</p>}
    </section>
  );
}
