import { copyFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const root = new URL('../', import.meta.url);
const target = new URL('openhmi/web/vendor/', root);
await mkdir(target, { recursive: true });
for (const [source, name] of [
  ['dist/grapes.min.js', 'grapes.min.js'],
  ['dist/css/grapes.min.css', 'grapes.min.css'],
  ['LICENSE', 'GRAPESJS-LICENSE.txt'],
]) {
  await copyFile(new URL(`node_modules/grapesjs/${source}`, root), new URL(name, target));
}
console.log(`Prepared GrapesJS core assets in ${fileURLToPath(target)}`);
