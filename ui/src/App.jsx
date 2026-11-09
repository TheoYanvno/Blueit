import { useState } from 'react';
import Find from './pages/Find.jsx';

const PAGES = [['find', 'Find stories']];

export default function App() {
  const [page, setPage] = useState('find');
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
      <main>{page === 'find' && <Find />}</main>
    </>
  );
}
