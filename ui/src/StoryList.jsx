// A list of stories as cards: title, where it's from, length, upvotes and status.
export default function StoryList({ stories, onOpen, actions }) {
  if (!stories.length) return <p className="muted">No stories here yet.</p>;
  return (
    <ul className="stories">
      {stories.map(s => (
        <li key={s.id} className="story">
          <div>
            <h3>{s.title}</h3>
            <div className="meta">
              r/{s.subreddit} · u/{s.author} · {s.words.toLocaleString()} words (~{s.minutes} min) · {s.score.toLocaleString()} upvotes
              {s.parts > 1 ? ` · ${s.parts} parts joined` : ''}
            </div>
          </div>
          <div className="row">
            <span className={`pill ${s.status}`}>{s.status}</span>
            {actions && actions(s)}
            {onOpen && <button onClick={() => onOpen(s.id)}>Open</button>}
          </div>
        </li>
      ))}
    </ul>
  );
}
