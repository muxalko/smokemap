import assert from "node:assert/strict";
import { test } from "node:test";
import { warmFrontend } from "../e2e/frontend-readiness.mjs";

test("readiness waits for the streamed homepage body, not just HTTP headers", async (t) => {
  let finishBody;
  const body = new Promise((resolve) => { finishBody = resolve; });
  let ready = false;
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url.href, "http://frontend:3000/");
    assert.equal(options.redirect, "error");
    assert.ok(options.signal instanceof AbortSignal);
    return { status: 200, arrayBuffer: () => body };
  });
  const warming = warmFrontend("http://frontend:3000").then(() => { ready = true; });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(ready, false);
  finishBody(new ArrayBuffer(0));
  await warming;
  assert.equal(ready, true);
});

for (const status of [204, 302, 503]) {
  test(`HTTP ${status} fails readiness`, async (t) => {
    t.mock.method(globalThis, "fetch", async () => ({ status }));
    await assert.rejects(warmFrontend("http://frontend:3000"), /HTTP 200/);
  });
}

for (const phase of ["request", "body"]) {
  test(`${phase} failure prevents browser startup`, async (t) => {
    t.mock.method(globalThis, "fetch", async () => {
      if (phase === "request") throw new Error("connection refused");
      return { status: 200, arrayBuffer: async () => { throw new Error("stream failed"); } };
    });
    await assert.rejects(warmFrontend("http://frontend:3000"), /connection refused|stream failed/);
  });
}

test("a hung response body fails within the startup deadline", async (t) => {
  t.mock.method(globalThis, "fetch", async (_url, { signal }) => ({
    status: 200,
    arrayBuffer: () => new Promise((_resolve, reject) => {
      signal.addEventListener("abort", () => reject(signal.reason), { once: true });
    }),
  }));
  // AbortSignal's timer is unref'ed; keep this isolated test process alive.
  const keepAlive = setTimeout(() => {}, 1000);
  try {
    await assert.rejects(warmFrontend("http://frontend:3000", 5), { name: "TimeoutError" });
  } finally {
    clearTimeout(keepAlive);
  }
});
