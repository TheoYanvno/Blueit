// Talks to the Blueit server (python -m blueit ui). GET for reading, POST with JSON for actions;
// an error from the server comes back as a thrown Error with the server's message.

export async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  let data;
  try {
    data = await res.json();
  } catch {
    throw new Error(`The server answered ${res.status} without data.`);
  }
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

export const get = (path, params = {}) => {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== '' && v != null)).toString();
  return api(q ? `${path}?${q}` : path);
};
