const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const http = require('node:http');
const { test } = require('node:test');

// Exercise the rendered Compose command, changing only its loopback port.
const probe = process.argv[2];
assert.ok(probe.includes('http://127.0.0.1:3000/favicon.ico'));

async function runProbe(port) {
  const code = probe.replace('127.0.0.1:3000', `127.0.0.1:${port}`);
  const child = spawn(process.execPath, ['-e', code], { stdio: ['ignore', 'pipe', 'pipe'] });
  let output = '';
  child.stdout.on('data', data => { output += data; });
  child.stderr.on('data', data => { output += data; });
  const deadline = setTimeout(() => child.kill('SIGKILL'), 5000);
  try {
    const [status, signal] = await once(child, 'exit');
    assert.equal(signal, null, 'probe must exit before Docker kills it');
    assert.equal(output, '', 'probe must not log response or exception text');
    return status;
  } finally {
    clearTimeout(deadline);
  }
}

for (const status of [200, 204, 302, 503]) {
  test(`static HEAD returns ${status}`, async () => {
    let requests = 0;
    const server = http.createServer((req, res) => {
      requests++;
      assert.equal(req.method, 'HEAD');
      assert.equal(req.url, '/favicon.ico');
      res.writeHead(status, { Location: '/' });
      res.end();
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    try {
      assert.equal(await runProbe(server.address().port), status === 200 ? 0 : 1);
      assert.equal(requests, 1, 'redirects must never render the homepage');
    } finally {
      server.closeAllConnections();
      server.close();
    }
  });
}

test('hung HTTP response fails within the probe budget', async () => {
  const server = http.createServer(() => {});
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const started = Date.now();
    assert.equal(await runProbe(server.address().port), 1);
    assert.ok(Date.now() - started < 4800, 'abort must precede Docker timeout');
  } finally {
    server.closeAllConnections();
    server.close();
  }
});

test('connection refused fails closed', async () => {
  const server = http.createServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  assert.equal(await runProbe(port), 1);
});
