// Bundles our entry points with esbuild and compiles the Enketo 'plain' theme with sass.
import * as esbuild from 'esbuild';
import * as sass from 'sass';
import { writeFileSync, mkdirSync, statSync } from 'node:fs';
import { gzipSync } from 'node:zlib';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const out = path.resolve('dist');
mkdirSync(out, { recursive: true });
const common = {
    bundle: true, minify: true, format: 'iife', platform: 'browser', target: 'es2020',
    alias: { 'enketo/config': './src/config.js' }, logLevel: 'warning', legalComments: 'external',
};
await esbuild.build({ ...common, entryPoints: ['src/app.js'], outfile: 'dist/app.js', metafile: true })
    .then((r) => writeFileSync('dist/app.meta.json', JSON.stringify(r.metafile)));
await esbuild.build({ ...common, entryPoints: ['src/app.js'], outfile: 'dist/app-slim.js',
    alias: { ...common.alias, 'enketo/widgets': './src/widgets-slim.js' } });
await esbuild.build({ ...common, entryPoints: ['src/xpath-entry.js'], outfile: 'dist/xpath.js' });
await esbuild.build({ ...common, entryPoints: ['src/transformer-entry.js'], outfile: 'dist/transformer.js', external: ['libxslt'] });
const css = sass.compile('node_modules/enketo-core/src/sass/plain/plain.scss', {
    style: 'compressed', loadPaths: ['node_modules'], silenceDeprecations: ['import', 'global-builtin', 'color-functions', 'slash-div'], quietDeps: true, verbose: false,
    logger: sass.Logger.silent,
    // enketo-core's published SCSS imports monorepo-absolute paths; map them onto our node_modules.
    importers: [{ findFileUrl(url) {
        const m = url.match(/^\/packages\/enketo-core\/node_modules\/(.*)$/);
        return m ? new URL('file://' + path.resolve('node_modules', m[1])) : null;
    } }],
});
writeFileSync('dist/plain.css', css.css);
const sizes = {};
for (const f of ['app.js', 'app-slim.js', 'plain.css', 'xpath.js', 'transformer.js']) {
    const b = readFileSync(path.join(out, f));
    sizes[f] = { bytes: statSync(path.join(out, f)).size, gzip: gzipSync(b).length };
}
writeFileSync('dist/sizes.json', JSON.stringify(sizes, null, 1));
console.log(JSON.stringify(sizes));
