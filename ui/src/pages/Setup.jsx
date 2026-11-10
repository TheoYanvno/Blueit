import { useEffect, useState } from 'react';
import { get } from '../api.js';

const LABELS = {
  subreddits: 'Subreddits', search: 'Search words', time_filter: 'Time', limit: 'Posts to check', min_words: 'Fewest words',
  max_words: 'Most words', min_score: 'Fewest upvotes', allow_nsfw: 'Allow NSFW', output: 'Video folder', images: 'Pictures folder',
  clip_seconds: 'Part length (seconds)', library: 'Library file', video_size: 'Video size', captions: 'Burn in captions',
  picture_seconds: 'Seconds per picture', shuffle_pictures: 'Shuffle pictures', voice_engine: 'Voice engine', voice: 'Voice', voice_rate: 'Voice speed',
};

function show(v) {
  if (Array.isArray(v)) return v.join(', ');
  if (v === true) return 'yes';
  if (v === false) return 'no';
  if (v === '') return 'none';
  if (v === null) return '(default)';
  return String(v);
}

// Setup: the same checks as `blueit doctor` (with how to fix anything missing) and the current
// settings from blueit.toml.
export default function Setup() {
  const [checks, setChecks] = useState(null);
  const [settings, setSettings] = useState(null);
  const [error, setError] = useState('');
  const [running, setRunning] = useState(false);

  async function runChecks() {
    setRunning(true); setError('');
    try { setChecks(await get('/api/doctor')); } catch (e) { setError(e.message); } finally { setRunning(false); }
  }

  useEffect(() => {
    runChecks();
    get('/api/settings').then(d => setSettings(d.settings)).catch(e => setError(e.message));
  }, []);

  return (
    <section className="setup" aria-labelledby="setup-title">
      <h2 id="setup-title">Setup</h2>
      <div className="row">
        <h3>Checks</h3>
        <button onClick={runChecks} disabled={running}>{running ? 'Checking…' : 'Check again'}</button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {checks ? (
        <>
          <p className={checks.ok ? 'ok' : 'error'}>{checks.ok ? '✓ Everything Blueit needs is ready.' : 'Some things need fixing before you make a video:'}</p>
          <ul className="checks">
            {checks.checks.map(c => (
              <li key={c.name} className={c.ok ? 'ok' : 'bad'}>
                <span aria-hidden="true">{c.ok ? '✓' : '✗'}</span>
                <span><strong>{c.name}</strong><span className="sr-only">{c.ok ? ' ready' : ' needs fixing'}</span><br /><span className="muted small">{c.detail}</span></span>
              </li>
            ))}
          </ul>
        </>
      ) : !error && <p className="muted">Running the checks…</p>}

      <h3>Settings</h3>
      <p className="muted small">To change these, edit <code>blueit.toml</code> in your Blueit folder (see <code>blueit.example.toml</code>), then restart <code>blueit ui</code>.</p>
      {settings && (
        <table className="settings">
          <tbody>
            {Object.entries(settings).map(([k, v]) => <tr key={k}><th scope="row">{LABELS[k] || k}</th><td>{show(v)}</td></tr>)}
          </tbody>
        </table>
      )}
    </section>
  );
}
