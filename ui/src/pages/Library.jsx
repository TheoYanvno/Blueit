import { useEffect, useState } from 'react';
import { api, get } from '../api.js';
import StoryList from '../StoryList.jsx';

// Library: every story saved so far, searchable by words, kind and status, with a button to mark
// each one narrated (or back to new).
export default function Library({ onOpen }) {
  const [filters, setFilters] = useState({ words: '', status: '', kind: '' });
  const [kinds, setKinds] = useState([]);
  const [data, setData] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => { get('/api/options').then(o => setKinds(o.kinds)).catch(() => {}); }, []);

  useEffect(() => {
    let alive = true;
    const t = setTimeout(() => {
      get('/api/library', filters)
        .then(d => { if (alive) { setData(d); setError(''); } })
        .catch(e => alive && setError(e.message));
    }, 200);                                   // wait for typing to pause before searching
    return () => { alive = false; clearTimeout(t); };
  }, [filters]);

  async function toggle(s) {
    try {
      const { story } = await api('/api/mark', { id: s.id, status: s.status === 'new' ? 'narrated' : 'new' });
      setData(d => ({ ...d, stories: d.stories.map(x => (x.id === story.id ? story : x)) }));
    } catch (e) {
      setError(e.message);
    }
  }

  const set = (k, v) => setFilters(f => ({ ...f, [k]: v }));
  return (
    <section aria-labelledby="lib-title">
      <h2 id="lib-title">Library</h2>
      {data && <p className="muted">{Object.entries(data.counts).map(([k, n]) => `${n} ${k}`).join(' · ')}</p>}
      <div className="filters">
        <label>Search<input value={filters.words} onChange={e => set('words', e.target.value)} placeholder="words in the title or text" /></label>
        <label>Status
          <select value={filters.status} onChange={e => set('status', e.target.value)}>
            <option value="">Any</option><option value="new">New</option><option value="narrated">Narrated</option>
          </select>
        </label>
        <label>Kind
          <select value={filters.kind} onChange={e => set('kind', e.target.value)}>
            <option value="">Any</option>
            {kinds.map(k => <option key={k.id} value={k.id}>{k.label}</option>)}
          </select>
        </label>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {data ? (
        <StoryList stories={data.stories} onOpen={onOpen}
          actions={s => <button onClick={() => toggle(s)}>{s.status === 'new' ? 'Mark narrated' : 'Mark new'}</button>} />
      ) : <p className="muted">Loading…</p>}
    </section>
  );
}
