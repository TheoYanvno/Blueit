import { useEffect, useState } from 'react';
import { api, get } from '../api.js';
import ShareYouTube from '../ShareYouTube.jsx';

// One story: its text, a Make video button that starts the narration and video in the background,
// and players for the full video and each 1-minute part once they're made.
export default function Story({ id, onBack, onStarted, nudge }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [showText, setShowText] = useState(false);
  const [playing, setPlaying] = useState(null);

  useEffect(() => {
    let alive = true;
    get('/api/story', { id }).then(d => {
      if (!alive) return;
      setData(d); setError('');
      setPlaying(p => p || d.full || d.parts[0] || null);
    }).catch(e => alive && setError(e.message));
    return () => { alive = false; };
  }, [id, nudge]);

  async function make() {
    setBusy(true); setError('');
    try {
      await api('/api/make', { id });
      onStarted();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (error && !data) return <section><button onClick={onBack}>← Back</button><p className="error" role="alert">{error}</p></section>;
  if (!data) return <p className="muted">Loading…</p>;
  const s = data.story;
  const media = name => `/media/${encodeURIComponent(data.folder)}/${encodeURIComponent(name)}`;
  const videos = [data.full, ...data.parts].filter(Boolean);

  return (
    <section className="story-page" aria-labelledby="story-title">
      <button onClick={onBack}>← Back</button>
      <h2 id="story-title">{s.title}</h2>
      <p className="muted">
        r/{s.subreddit} · u/{s.author} · {s.words.toLocaleString()} words (~{s.minutes} min) · {s.score.toLocaleString()} upvotes
        {' · '}<span className={`pill ${s.status}`}>{s.status}</span>
      </p>
      <div className="row">
        <button className="primary" disabled={busy} onClick={make}>{videos.length ? 'Make the video again' : 'Make video'}</button>
        <a className="button" href={s.url} target="_blank" rel="noreferrer noopener">Read on Reddit</a>
      </div>
      {error && <p className="error" role="alert">{error}</p>}

      {videos.length > 0 ? (
        <div className="player">
          <video key={playing} src={media(playing)} controls preload="metadata" aria-label={`Video: ${playing}`} />
          <ul className="videos" aria-label="Videos">
            {videos.map(v => (
              <li key={v}>
                <button aria-pressed={playing === v} onClick={() => setPlaying(v)}>{v === 'full.mp4' ? 'Full video' : v.replace('part-', 'Part ').replace('.mp4', '')}</button>
                <a href={media(v)} download>Download</a>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {videos.length > 0 && <ShareYouTube storyId={s.id} videos={videos} current={playing} />}
      {videos.length > 0 ? null : <p className="muted">No video yet. Press Make video: the narration and video are made in the background, and the bar at the top shows how far along it is.</p>}

      {data.files.some(f => !f.endsWith('.mp4')) && (
        <p className="muted small">Other files: {data.files.filter(f => !f.endsWith('.mp4')).map(f => (
          <a key={f} href={media(f)} target="_blank" rel="noreferrer">{f}</a>
        )).reduce((acc, el, i) => (i ? [...acc, ', ', el] : [el]), [])}</p>
      )}

      <button onClick={() => setShowText(t => !t)} aria-expanded={showText}>{showText ? 'Hide the story' : 'Show the story'}</button>
      {showText && <pre className="story-text">{s.body}</pre>}
    </section>
  );
}
