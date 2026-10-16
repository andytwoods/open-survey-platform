// e2e server: serves the built harness on APP_PORT and runs a cross-origin canary on
// CANARY_PORT. Every request that is not a harness file (on either port, including
// WebSocket upgrades) is an egress attempt and is logged. GET /__log returns the log,
// POST /__reset clears it. Only the test runner calls those two.
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';

const APP_PORT = Number(process.env.APP_PORT ?? 4417);
const CANARY_PORT = Number(process.env.CANARY_PORT ?? 4418);
const ROOT = fileURLToPath(new URL('./build', import.meta.url));
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.map': 'application/json' };

let hits = [];
const log = (server, req, kind = 'http') =>
	hits.push({ server, kind, method: req.method, url: req.url, origin: req.headers.origin ?? null, at: Date.now() });

const app = createServer(async (req, res) => {
	const url = new URL(req.url, `http://127.0.0.1:${APP_PORT}`);
	if (url.pathname === '/__log') {
		res.writeHead(200, { 'content-type': 'application/json', 'cache-control': 'no-store' });
		return res.end(JSON.stringify(hits));
	}
	if (url.pathname === '/__reset' && req.method === 'POST') {
		hits = [];
		res.writeHead(204);
		return res.end();
	}
	if (url.pathname === '/favicon.ico') {
		res.writeHead(404);
		return res.end();
	}
	const path = url.pathname === '/' ? '/index.html' : url.pathname;
	const file = normalize(join(ROOT, path));
	if (file.startsWith(ROOT) && req.method === 'GET') {
		try {
			const body = await readFile(file);
			res.writeHead(200, { 'content-type': TYPES[extname(file)] ?? 'application/octet-stream', 'cache-control': 'no-store' });
			return res.end(body);
		} catch {
			/* not a harness file: an egress attempt */
		}
	}
	log('app', req);
	res.writeHead(404, { 'access-control-allow-origin': '*' });
	res.end('egress');
});

const canary = createServer((req, res) => {
	log('canary', req);
	res.writeHead(200, { 'access-control-allow-origin': '*', 'content-type': 'text/plain' });
	res.end('canary');
});

for (const [name, server] of [
	['app', app],
	['canary', canary]
]) {
	server.on('upgrade', (req, socket) => {
		log(name, req, 'websocket');
		socket.destroy();
	});
}

app.listen(APP_PORT, '127.0.0.1');
canary.listen(CANARY_PORT, '127.0.0.1');
console.log(`hooks e2e server on ${APP_PORT}, canary on ${CANARY_PORT}`);
