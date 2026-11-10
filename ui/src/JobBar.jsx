import { useEffect, useState } from 'react';
import { get } from './api.js';

// The video being made in the background, shown on every page: its step and a progress bar while it
// runs, then "done" with the number of parts, or the error. Checks every 1.5 seconds while running.
export default function JobBar({ nudge, onDone }) {
  const [job, setJob] = useState({ state: 'idle' });

  useEffect(() => {
    let alive = true;
    let timer;
    async function poll() {
      try {
        const j = await get('/api/job');
        if (!alive) return;
        setJob(prev => {
          if (prev.state === 'running' && j.state !== 'running' && onDone) setTimeout(onDone, 0);   // let pages reload their files
          return j;
        });
        if (j.state === 'running') timer = setTimeout(poll, 1500);
      } catch {
        if (alive) timer = setTimeout(poll, 5000);
      }
    }
    poll();
    return () => { alive = false; clearTimeout(timer); };
  }, [nudge]);

  if (job.state === 'idle') return null;
  const pct = job.total ? Math.round((job.done / job.total) * 100) : null;
  return (
    <div className={`jobbar ${job.state}`} role="status" aria-live="polite">
      {job.state === 'running' && <>Making <strong>{job.title}</strong>: {job.step}{pct !== null ? ` (${pct}%)` : '…'}
        <progress max="100" value={pct ?? undefined} /></>}
      {job.state === 'done' && <>✓ Finished <strong>{job.title}</strong>{job.parts ? ` — full video and ${job.parts} part${job.parts === 1 ? '' : 's'}` : ''}</>}
      {job.state === 'error' && <>✗ Couldn't make <strong>{job.title}</strong>: {job.error}</>}
    </div>
  );
}
