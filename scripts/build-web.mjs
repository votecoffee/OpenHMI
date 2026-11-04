import { copyFile, mkdir, readdir, readFile, rm, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const root = new URL('../', import.meta.url);
const target = new URL('openhmi/web/vendor/', root);
await mkdir(target, { recursive: true });
for (const name of ['grapes.min.js', 'grapes.min.css', 'GRAPESJS-LICENSE.txt']) {
  await rm(new URL(name, target), { force: true });
}
await build({
  entryPoints: [fileURLToPath(new URL('frontend/app.jsx', root))],
  outdir: fileURLToPath(target), bundle: true, format: 'esm', minify: true,
  target: 'es2022', define: { 'process.env.NODE_ENV': '"production"' },
  external: ['/static/*'],
  legalComments: 'linked',
});
for (const [source, name] of [
  ['@puckeditor/core/LICENSE', 'PUCK-LICENSE.txt'],
  ['react/LICENSE', 'REACT-LICENSE.txt'],
  ['react-dom/LICENSE', 'REACT-DOM-LICENSE.txt'],
]) {
  await copyFile(new URL(`node_modules/${source}`, root), new URL(name, target));
}
// Ship dependency license texts as well as esbuild's linked bundle notices.
let notices = 'OpenHMI browser dependency license archive\n\n';
async function collect(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  for (const entry of entries) {
    if (!entry.isDirectory() || entry.name.startsWith('.')) continue;
    const packageDir = new URL(`${entry.name}/`, directory);
    if (entry.name.startsWith('@')) { await collect(packageDir); continue; }
    const files = await readdir(packageDir);
    if (!files.includes('package.json')) continue;
    const pkg = JSON.parse(await readFile(new URL('package.json', packageDir), 'utf8'));
    notices += `===== ${pkg.name} ${pkg.version} (${pkg.license || 'see package'}) =====\n`;
    for (const name of files.filter(name => /^(license|licence|copying|notice)(\.|$)/i.test(name))) {
      notices += `${await readFile(new URL(name, packageDir), 'utf8')}\n`;
    }
    if (files.includes('node_modules')) await collect(new URL('node_modules/', packageDir));
  }
}
await collect(new URL('node_modules/', root));
await writeFile(new URL('THIRD-PARTY-LICENSES.txt', target), notices, 'utf8');
console.log(`Prepared OpenHMI / Puck assets in ${fileURLToPath(target)}`);
