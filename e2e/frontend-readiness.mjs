import assert from "node:assert/strict";

// Static Compose liveness does not compile Next's development homepage.
// Pay that one-time startup cost before starting browser interaction budgets.
export async function warmFrontend(baseUrl, timeoutMs = 120_000) {
  const response = await fetch(new URL("/", baseUrl), {
    redirect: "error",
    signal: AbortSignal.timeout(timeoutMs),
  });
  assert.equal(response.status, 200, "E2E homepage readiness must return HTTP 200");
  // Next streams HTML: receiving headers alone does not finish compilation.
  await response.arrayBuffer();
}
