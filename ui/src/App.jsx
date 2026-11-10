import { useState } from 'react';
import Find from './pages/Find.jsx';
import Library from './pages/Library.jsx';
import Story from './pages/Story.jsx';
import Setup from './pages/Setup.jsx';
import JobBar from './JobBar.jsx';

const PAGES = [['find', 'Find stories'], ['library', 'Library'], ['setup', 'Setup']];

export default function App() {
  const [page, setPage] = useState('find');
  const [nudge, setNudge] = useState(0);         // bump to make the job bar check again
  const [openId, setOpenId] = useState(null);
  function go(id) { setPage(id); setOpenId(null); }
  return (
    <>
      <header>
        <h1>▶ Blueit</h1>
        <nav aria-label="Pages">
          {PAGES.map(([id, label]) => (
            <button key={id} aria-current={page === id && !openId ? 'page' : undefined} onClick={() => go(id)}>{label}</button>
          ))}
        </nav>
      </header>
      <JobBar nudge={nudge} onDone={() => setNudge(n => n + 1)} />
      <main>
        {openId ? <Story id={openId} nudge={nudge} onBack={() => setOpenId(null)} onStarted={() => setNudge(n => n + 1)} />
          : page === 'find' ? <Find onOpen={setOpenId} />
          : page === 'setup' ? <Setup />
          : <Library onOpen={setOpenId} />}
      </main>
    </>
  );
}
