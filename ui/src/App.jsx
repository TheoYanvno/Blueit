import { useState } from 'react';
import Find from './pages/Find.jsx';
import Library from './pages/Library.jsx';
import JobBar from './JobBar.jsx';

const PAGES = [['find', 'Find stories'], ['library', 'Library']];

export default function App() {
  const [page, setPage] = useState('find');
  const [nudge, setNudge] = useState(0);         // bump to make the job bar check again
  return (
    <>
      <header>
        <h1>▶ Blueit</h1>
        <nav aria-label="Pages">
          {PAGES.map(([id, label]) => (
            <button key={id} aria-current={page === id ? 'page' : undefined} onClick={() => setPage(id)}>{label}</button>
          ))}
        </nav>
      </header>
      <JobBar nudge={nudge} />
      <main>
        {page === 'find' && <Find />}
        {page === 'library' && <Library />}
      </main>
    </>
  );
}
