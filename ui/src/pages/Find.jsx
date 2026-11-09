import { useEffect, useState } from 'react';
import { api, get } from '../api.js';
import StoryList from '../StoryList.jsx';

// Find stories: the same drop-down menus as `blueit fetch` (kind, subreddit, time, length, upvotes,
// how many posts), then the finished stories that search found.
export default function Find({ onOpen }) {
  const [options, setOptions] = useState(null);
  const [form, setForm] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    get('/api/options').then(o => {
      setOptions(o);
      setForm({ ...o.defaults, subreddit: '', words: '' });
    }).catch(e => setError(e.message));
  }, []);

  if (error && !options) return <p className="error" role="alert">{error}</p>;
  if (!options || !form) return <p className="muted">Loading the menus…</p>;

  const kind = options.kinds.find(k => k.id === form.kind);
  const set = (key, value) => setForm(f => ({ ...f, [key]: value, ...(key === 'kind' ? { subreddit: '' } : {}) }));

  async function search(e) {
    e.preventDefault();
    setBusy(true); setError(''); setResult(null);
    try {
      const data = await api('/api/find', form);
      if (!data.ok) setError(data.error);
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="find-title">
      <h2 id="find-title">Find stories</h2>
      <p className="muted">Searches Reddit with these choices and keeps only finished stories. Everything found is saved to your library.</p>
      <form className="filters" onSubmit={search}>
        <Select label="Kind of story" value={form.kind} onChange={v => set('kind', v)} items={options.kinds.map(k => [k.id, k.label])} />
        <Select label="Subreddit" value={form.subreddit} onChange={v => set('subreddit', v)}
          items={[['', `All ${kind ? kind.subreddits.length : ''}`], ...(kind ? kind.subreddits.map(s => [s, `r/${s}`]) : [])]} />
        <Select label="Posted in the last" value={form.time} onChange={v => set('time', v)} items={options.times.map(t => [t.id, t.label])} />
        <Select label="Length" value={form.length} onChange={v => set('length', v)} items={options.lengths.map(l => [l.id, l.label])} />
        <Select label="At least this many upvotes" value={form.minScore} onChange={v => set('minScore', Number(v))} items={options.minScores.map(n => [n, n.toLocaleString()])} />
        <Select label="Posts to look at" value={form.limit} onChange={v => set('limit', Number(v))} items={options.limits.map(n => [n, String(n)])} />
        <label>Words (optional)<input value={form.words} maxLength={100} onChange={e => set('words', e.target.value)} placeholder="e.g. lighthouse" /></label>
        <button className="primary" disabled={busy}>{busy ? 'Searching…' : 'Find stories'}</button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      {result && (
        <>
          <p className="muted" aria-live="polite">{result.stories.length} finished {result.stories.length === 1 ? 'story' : 'stories'} found.</p>
          <StoryList stories={result.stories} onOpen={onOpen} />
          {result.log.length > 0 && <details><summary className="muted">Search log</summary><pre>{result.log.join('\n')}</pre></details>}
        </>
      )}
    </section>
  );
}

function Select({ label, value, onChange, items }) {
  return (
    <label>{label}
      <select value={value} onChange={e => onChange(e.target.value)}>
        {items.map(([v, text]) => <option key={v} value={v}>{text}</option>)}
      </select>
    </label>
  );
}
