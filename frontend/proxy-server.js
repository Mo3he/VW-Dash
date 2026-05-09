#!/usr/bin/env node
/**
 * Thin proxy that sits in front of the Next.js standalone server.
 *   HTTP  → Next.js on localhost:3001
 *   WS /ws → FastAPI on localhost:8000
 *
 * This means only one port (3000) needs to be exposed to the outside world.
 */
const http = require('http');
const net = require('net');
const { spawn } = require('child_process');
const path = require('path');

const PORT = parseInt(process.env.PORT || '3000');
const HOSTNAME = process.env.HOSTNAME || '0.0.0.0';
const NEXT_PORT = 3001;
const BACKEND_PORT = parseInt(process.env.BACKEND_PORT || '8000');

// Start the Next.js standalone server on an internal port
const next = spawn(process.execPath, [path.join(__dirname, 'server.js')], {
  env: { ...process.env, PORT: String(NEXT_PORT), HOSTNAME: '127.0.0.1' },
  stdio: 'inherit',
});
next.on('error', (err) => { console.error('Next.js error:', err); process.exit(1); });
next.on('exit', (code) => { console.error(`Next.js exited (${code})`); process.exit(code ?? 1); });

setTimeout(() => {
  const server = http.createServer((req, res) => {
    const proxy = http.request(
      { hostname: '127.0.0.1', port: NEXT_PORT, path: req.url, method: req.method,
        headers: { ...req.headers, host: `localhost:${NEXT_PORT}` } },
      (upstream) => { res.writeHead(upstream.statusCode, upstream.headers); upstream.pipe(res); }
    );
    proxy.on('error', () => { res.writeHead(502); res.end(); });
    req.pipe(proxy);
  });

  // Proxy WebSocket upgrades directly to FastAPI (bypasses Next.js)
  server.on('upgrade', (req, clientSocket, head) => {
    const backendSocket = net.connect(BACKEND_PORT, '127.0.0.1');
    backendSocket.on('connect', () => {
      const lines = [`${req.method} ${req.url} HTTP/1.1`];
      for (const [k, v] of Object.entries(req.headers)) lines.push(`${k}: ${v}`);
      lines.push('', '');
      backendSocket.write(lines.join('\r\n'));
      if (head?.length) backendSocket.write(head);
      backendSocket.pipe(clientSocket);
      clientSocket.pipe(backendSocket);
    });
    backendSocket.on('error', () => clientSocket.destroy());
    clientSocket.on('error', () => backendSocket.destroy());
  });

  server.listen(PORT, HOSTNAME, () =>
    console.log(`VW-Dash listening on ${HOSTNAME}:${PORT}`)
  );
}, 2000);
