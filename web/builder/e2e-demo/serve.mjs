// A plain static file server for the demo e2e (task DEMO2): build-demo/ under the same
// path as on GitHub Pages (/open-survey-platform/demo/), nothing else. No API, no proxy,
// no rewrites: what the tests see is what Pages serves.
//
//     node e2e-demo/serve.mjs [port]
import { createReadStream, statSync } from 'node:fs';
import { createServer } from 'node:http';
import { extname, join, normalize, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

export const PREFIX = '/open-survey-platform/demo/';
const ROOT = fileURLToPath(new URL('../build-demo/', import.meta.url));
const port = Number(process.argv[2] ?? process.env.OSP_PAGES_DEMO_PORT ?? 6437);

const TYPES = {
	'.html': 'text/html; charset=utf-8',
	'.js': 'text/javascript; charset=utf-8',
	'.css': 'text/css; charset=utf-8',
	'.json': 'application/json',
	'.svg': 'image/svg+xml',
	'.png': 'image/png',
	'.woff2': 'font/woff2',
	'.webmanifest': 'application/manifest+json'
};

createServer((req, res) => {
	const url = new URL(req.url ?? '/', 'http://localhost');
	if (url.pathname === '/open-survey-platform/demo') {
		res.writeHead(301, { location: PREFIX });
		return res.end();
	}
	if (!url.pathname.startsWith(PREFIX)) {
		res.writeHead(404);
		return res.end('not found');
	}
	let rel;
	try {
		rel = decodeURIComponent(url.pathname.slice(PREFIX.length));
	} catch {
		res.writeHead(400);
		return res.end();
	}
	let file = normalize(join(ROOT, rel));
	if (!file.startsWith(ROOT.endsWith(sep) ? ROOT : ROOT + sep) && file + sep !== ROOT) {
		res.writeHead(403);
		return res.end();
	}
	try {
		if (statSync(file).isDirectory()) {
			// As Pages does: a directory without its slash redirects, so relative URLs work.
			if (!url.pathname.endsWith('/')) {
				res.writeHead(301, { location: `${url.pathname}/${url.search}` });
				return res.end();
			}
			file = join(file, 'index.html');
		}
		statSync(file);
	} catch {
		res.writeHead(404);
		return res.end('not found');
	}
	res.writeHead(200, { 'content-type': TYPES[extname(file)] ?? 'application/octet-stream' });
	createReadStream(file).pipe(res);
}).listen(port, '127.0.0.1', () => console.log(`demo: http://127.0.0.1:${port}${PREFIX}`));
