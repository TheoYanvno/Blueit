import { useEffect, useRef, useState } from 'react';
import { api, get } from '../api.js';
import { clock, toWav } from '../wav.js';

// Record my voice: read the script aloud for about five minutes, listen back, confirm it's your own
// voice and save it. Saved voices can be renamed, deleted, listened to (the 15-second clip Blueit
// copies) and made the default narrator. The recording stays on this computer.
export default function MyVoice() {
  const [info, setInfo] = useState(null);
  const [error, setError] = useState('');
  const [note, setNote] = useState('');
  const [name, setName] = useState('My voice');
  const [state, setState] = useState('idle');          // idle, recording, paused, done, saving
  const [seconds, setSeconds] = useState(0);
  const [level, setLevel] = useState(0);
  const [take, setTake] = useState(null);              // { blob, url }
  const [mine, setMine] = useState(false);
  const rec = useRef(null);

  const load = () => get('/api/voices').then(setInfo).catch((e) => setError(e.message));
  useEffect(() => { load(); return () => stopAll(); }, []);

  function stopAll() {
    const r = rec.current;
    if (!r) return;
    clearInterval(r.timer);
    cancelAnimationFrame(r.frame);
    r.stream?.getTracks().forEach((t) => t.stop());
    r.ctx?.close();
  }

  async function start() {
    setError(''); setNote('');
    if (take) URL.revokeObjectURL(take.url);
    setTake(null); setMine(false); setSeconds(0);
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
    } catch {
      setError('Blueit needs your microphone to record. Allow it in the browser (the icon in the address bar) and try again.');
      return;
    }
    const chunks = [];
    const media = new MediaRecorder(stream);
    media.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    media.onstop = () => {
      const blob = new Blob(chunks, { type: media.mimeType });
      setTake({ blob, url: URL.createObjectURL(blob) });
      setState('done');
      stopAll();
    };
    const ctx = new AudioContext();
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    ctx.createMediaStreamSource(stream).connect(analyser);
    const data = new Uint8Array(analyser.fftSize);
    const meter = () => {
      analyser.getByteTimeDomainData(data);
      let peak = 0;
      for (const x of data) peak = Math.max(peak, Math.abs(x - 128));
      setLevel(Math.min(1, peak / 100));
      rec.current.frame = requestAnimationFrame(meter);
    };
    rec.current = { media, stream, ctx, started: Date.now(), before: 0 };
    rec.current.timer = setInterval(() => {
      const r = rec.current;
      if (r.media.state === 'recording') setSeconds(r.before + (Date.now() - r.started) / 1000);
    }, 250);
    media.start(1000);
    meter();
    setState('recording');
  }

  function pause() {
    const r = rec.current;
    if (state === 'recording') { r.media.pause(); r.before += (Date.now() - r.started) / 1000; setState('paused'); }
    else { r.media.resume(); r.started = Date.now(); setState('recording'); }
  }

  function stop() { rec.current?.media.stop(); setLevel(0); }

  async function save() {
    setError(''); setState('saving');
    try {
      const wav = await toWav(take.blob);
      const res = await fetch(`/api/voices/upload?${new URLSearchParams({ name, mine: mine ? '1' : '0' })}`,
        { method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: wav });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Saving failed.');
      setInfo(data);
      setNote(`Saved "${name}". Listen to the clip Blueit picked below.`);
      URL.revokeObjectURL(take.url);
      setTake(null); setState('idle'); setSeconds(0);
    } catch (e) {
      setError(e.message); setState('done');
    }
  }

  async function act(body, done) {
    setError('');
    try { setInfo(await api('/api/voices', body)); if (done) setNote(done); } catch (e) { setError(e.message); }
  }

  function rename(v) {
    const next = prompt('New name for this voice', v.name);
    if (next && next.trim() && next.trim() !== v.name) act({ action: 'rename', voice: v.slug, name: next.trim() }, 'Renamed.');
  }

  function remove(v) {
    if (confirm(`Delete "${v.name}" and its recording? This can't be undone.`)) act({ action: 'delete', voice: v.slug }, 'Deleted.');
  }

  if (!info) return <section className="myvoice"><h2>My voice</h2>{error ? <p className="error" role="alert">{error}</p> : <p className="muted">Loading…</p>}</section>;
  const recording = state === 'recording' || state === 'paused';
  const enough = seconds >= info.minSeconds;

  return (
    <section className="myvoice" aria-labelledby="mv-title">
      <h2 id="mv-title">My voice</h2>
      <p className="muted">Record yourself reading the script below, about five minutes at your normal pace, and Blueit can narrate stories in your own voice. The recording stays on this computer, in the <code>voices</code> folder.</p>
      {!info.addon && (
        <p className="notice">The voice engine is an optional add-on (Chatterbox, about 2 GB). You can record and save your voice now; to narrate with it, run <code>pip install chatterbox-tts</code> once.</p>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      {note && <p className="ok" role="status">{note}</p>}

      <div className="record card">
        <h3>Record a voice</h3>
        <label>Name <input value={name} maxLength={60} onChange={(e) => setName(e.target.value)} disabled={recording} /></label>
        <div className="rec-row">
          {!recording ? <button className="primary" onClick={start}>{take ? '● Record again' : '● Start recording'}</button>
            : <><button onClick={pause}>{state === 'paused' ? '▶ Resume' : '❚❚ Pause'}</button><button className="primary" onClick={stop}>■ Stop</button></>}
          <span className="rec-time" aria-live="off">{clock(seconds)} <span className="muted">/ about {clock(info.suggestedSeconds)}</span></span>
          <span className="rec-meter" role="img" aria-label="Microphone level"><span style={{ width: `${Math.round(level * 100)}%` }} /></span>
        </div>
        {recording && <p className="muted small">{state === 'paused' ? 'Paused. Resume when you\'re ready.' : 'Recording. Read the script below at your normal pace, as if you were telling a friend.'}</p>}
        {take && (
          <div className="take">
            <audio controls src={take.url} />
            <label className="check"><input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> This is my own voice, and I agree to Blueit using it to narrate my videos.</label>
            {!enough && <p className="error">That's {Math.round(seconds)} seconds. Record at least {info.minSeconds} seconds (about five minutes is best).</p>}
            <button className="primary" onClick={save} disabled={!mine || !enough || state === 'saving'}>{state === 'saving' ? 'Saving…' : 'Save this voice'}</button>
          </div>
        )}
      </div>

      <details className="script card" open={recording || !info.voices.length}>
        <summary>The reading script</summary>
        {info.script.split('\n\n').map((p, i) => <p key={i}>{p}</p>)}
      </details>

      <div className="card">
        <h3>Saved voices</h3>
        {info.voices.length ? (
          <>
            <label className="check"><input type="checkbox" checked={info.narrator} onChange={(e) => act({ action: 'use', voice: info.default, on: e.target.checked }, e.target.checked ? 'Your voice is now the default narrator.' : 'Back to the stock voice.')} /> Use my voice as the default narrator</label>
            <ul className="voices">
              {info.voices.map((v) => (
                <li key={v.slug}>
                  <label className="check"><input type="radio" name="default-voice" checked={info.default === v.slug} onChange={() => act({ action: 'default', voice: v.slug }, `${v.name} is the default voice.`)} /> <strong>{v.name}</strong></label>
                  <span className="muted small">{clock(v.seconds)} recorded · saved {v.created}</span>
                  <audio controls preload="none" src={`/api/voices/clip?voice=${encodeURIComponent(v.slug)}&which=prompt`} aria-label={`The 15-second clip Blueit copies for ${v.name}`} />
                  <span className="voice-actions"><button className="link" onClick={() => rename(v)}>Rename</button> <button className="link danger" onClick={() => remove(v)}>Delete</button></span>
                </li>
              ))}
            </ul>
            <p className="muted small">The player plays the clearest 15 seconds of each recording: that's what the voice engine copies. Stories narrated in your voice get an "AI-generated narration" line in their credit.txt, since TikTok and YouTube ask you to label AI voices.</p>
          </>
        ) : <p className="muted">No saved voices yet.</p>}
      </div>
    </section>
  );
}
