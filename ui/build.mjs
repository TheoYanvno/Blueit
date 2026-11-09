// Builds the React app into ../blueit/static, which `python -m blueit ui` serves.
// `npm start` rebuilds on every change; run `python -m blueit ui` alongside it and refresh the page.
import * as esbuild from 'esbuild';
import { cp, mkdir, rm } from 'node:fs/promises';

const out = '../blueit/static';
const watch = process.argv.includes('--watch');
await rm(out, { recursive: true, force: true });
await mkdir(`${out}/assets`, { recursive: true });
await cp('public/index.html', `${out}/index.html`);
await cp('public/styles.css', `${out}/assets/styles.css`);
await cp('public/icon.svg', `${out}/assets/icon.svg`);

const options = {
  entryPoints: ['src/main.jsx'], bundle: true, outfile: `${out}/assets/app.js`, jsx: 'automatic',
  minify: !watch, target: ['es2020'], logLevel: 'info',
  define: { 'process.env.NODE_ENV': watch ? '"development"' : '"production"' },
};
if (watch) await (await esbuild.context(options)).watch();
else await esbuild.build(options);
