import { build } from 'esbuild';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const compiled = await build({
  entryPoints: [fileURLToPath(new URL('./frontend_contract_entry.jsx', import.meta.url))],
  bundle: true, platform: 'node', format: 'cjs', write: false, logLevel: 'silent',
  loader: { '.css': 'empty' },
});
// Evaluate only the locally built test entry, resolving packages from this repo.
const module = { exports: {} };
new Function('require', 'module', 'exports', compiled.outputFiles[0].text)(
  createRequire(import.meta.url), module, module.exports);
let input = '';
for await (const part of process.stdin) input += part;
process.stdout.write(JSON.stringify(await module.exports.contract(JSON.parse(input))));
