import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { deflateSync } from "node:zlib";

import puppeteer from "puppeteer";

const baseUrl = process.env.E2E_BASE_URL ?? "http://frontend:3000";
const basemapOrigin = "http://127.0.0.1:4173";
const storageOrigin = "http://storage:9000";
const stateDir = process.env.SMOKEMAP_E2E_STATE_DIR ?? "/workspace-e2e-state";
const phase = process.env.SMOKEMAP_E2E_PHASE;
const password =
  process.env.SMOKEMAP_LOCAL_TEST_PASSWORD ?? "Smokemap-local-test-only-2026!";
const ownerEmail = "user-one@smokemap.local";
const adminEmail = "admin@smokemap.local";
const categoryDisplayName = "Outdoors";
const approvedName = "Smokemap E2E Issue 100 Approved Media Place";
const rejectedName = "Smokemap E2E Issue 100 Rejected Media Place";
const withdrawnName = "Smokemap E2E Issue 100 Withdrawn Media Place";
const fixtureNames = [approvedName, rejectedName, withdrawnName];
const sourceMarkers = new Map([
  [approvedName, "smokemap-e2e-approved-source-metadata"],
  [rejectedName, "smokemap-e2e-rejected-source-metadata"],
  [withdrawnName, "smokemap-e2e-withdrawn-source-metadata"],
]);

assert.ok(["create", "lifecycle"].includes(phase), "SMOKEMAP_E2E_PHASE is invalid");

const basemapStyle = JSON.stringify({
  version: 8,
  name: "Smokemap deterministic public media E2E basemap",
  glyphs: `${basemapOrigin}/fonts/{fontstack}/{range}.pbf`,
  sources: {},
  layers: [{ id: "background", type: "background", paint: { "background-color": "#e5e7eb" } }],
});

function startBasemapServer() {
  const server = createServer((request, response) => {
    if (request.url?.startsWith("/fonts/") && request.url.endsWith(".pbf")) {
      response.writeHead(200, { "Access-Control-Allow-Origin": "*", "Content-Type": "application/x-protobuf" });
      response.end(Buffer.alloc(0));
      return;
    }
    if (request.url !== "/style.json") {
      response.writeHead(404).end();
      return;
    }
    response.writeHead(200, { "Access-Control-Allow-Origin": "*", "Cache-Control": "no-store", "Content-Type": "application/json" });
    response.end(basemapStyle);
  });
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(4173, "127.0.0.1", () => resolve(server));
  });
}

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let value = n;
    for (let bit = 0; bit < 8; bit += 1) {
      value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
    }
    table[n] = value >>> 0;
  }
  return table;
})();

function crc32(buffer) {
  let crc = 0xffffffff;
  for (const byte of buffer) crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function pngChunk(type, data) {
  const typeBuffer = Buffer.from(type, "ascii");
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length, 0);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([typeBuffer, data])), 0);
  return Buffer.concat([length, typeBuffer, data, crc]);
}

function fixturePng(marker, [red, green, blue]) {
  const width = 8;
  const height = 8;
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;
  ihdr[9] = 2;
  const row = Buffer.alloc(1 + width * 3);
  for (let x = 0; x < width; x += 1) {
    row[1 + x * 3] = red;
    row[2 + x * 3] = green;
    row[3 + x * 3] = blue;
  }
  const raw = Buffer.concat(Array.from({ length: height }, () => row));
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    pngChunk("IHDR", ihdr),
    pngChunk("tEXt", Buffer.from(`Comment\0${marker}`, "utf8")),
    pngChunk("IDAT", deflateSync(raw)),
    pngChunk("IEND", Buffer.alloc(0)),
  ]);
}

function writeFixtureImages() {
  const directory = mkdtempSync(join(tmpdir(), "smokemap-public-media-e2e-"));
  const colors = [[220, 20, 60], [30, 144, 255], [34, 139, 34]];
  return fixtureNames.map((name, index) => {
    const path = join(directory, `fixture-${index}.png`);
    writeFileSync(path, fixturePng(sourceMarkers.get(name), colors[index]));
    return path;
  });
}

async function findVisibleByExactText(page, selector, text) {
  return page.evaluateHandle(
    (sel, expected) => Array.from(document.querySelectorAll(sel)).find((element) => {
      const bounds = element.getBoundingClientRect();
      return element.textContent?.trim() === expected && bounds.width > 0 && bounds.height > 0;
    }) ?? null,
    selector,
    text,
  );
}

async function clickVisibleByExactText(page, selector, text, timeout = 15_000) {
  await page.waitForFunction(
    (sel, expected) => Array.from(document.querySelectorAll(sel)).some((element) => {
      const bounds = element.getBoundingClientRect();
      return element.textContent?.trim() === expected && bounds.width > 0 && bounds.height > 0;
    }),
    { timeout },
    selector,
    text,
  );
  const handle = await findVisibleByExactText(page, selector, text);
  const element = handle.asElement();
  assert.ok(element, `no visible ${selector} matched ${text}`);
  await element.click();
  await handle.dispose();
}

async function waitForVisibleText(page, text, timeout = 15_000) {
  await page.waitForFunction(
    (expected) => Array.from(document.querySelectorAll("*")).some((element) => {
      const bounds = element.getBoundingClientRect();
      return element.textContent?.includes(expected) && bounds.width > 0 && bounds.height > 0;
    }),
    { timeout },
    text,
  );
}

async function retryClickUntil(clickAction, expectAction, attempts = 4) {
  let lastError;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    await clickAction();
    try {
      await expectAction();
      return;
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError;
}

async function signIn(page, email, callbackPath) {
  await page.goto(
    `${baseUrl}/api/auth/signin?callbackUrl=${encodeURIComponent(`${baseUrl}${callbackPath}`)}`,
    { waitUntil: "domcontentloaded", timeout: 30_000 },
  );
  await (await page.waitForSelector('input[name="email"]', { visible: true })).type(email);
  await (await page.waitForSelector('input[name="password"]', { visible: true })).type(password);
  await Promise.all([
    page.waitForNavigation({ waitUntil: "domcontentloaded", timeout: 30_000 }),
    page.click('button[type="submit"]'),
  ]);
}

async function fillSubmission(page, name, filePath) {
  await retryClickUntil(
    () => clickVisibleByExactText(page, "button", "+"),
    () => waitForVisibleText(page, "Submit a place", 5_000),
  );
  const nameInput = await page.waitForSelector('input[placeholder="Place name"]', { visible: true });
  await nameInput.click({ clickCount: 3 });
  await nameInput.type(name);
  await retryClickUntil(
    async () => (await page.waitForSelector('button[role="combobox"]', { visible: true })).click(),
    () => page.waitForSelector("[cmdk-item]", { visible: true, timeout: 5_000 }),
  );
  await clickVisibleByExactText(page, "[cmdk-item]", categoryDisplayName);
  await page.waitForSelector("[cmdk-item]", { hidden: true });
  await retryClickUntil(
    () => clickVisibleByExactText(page, "button", "Choose location on map"),
    () => page.waitForSelector('button[aria-label="Confirm submission location"]', { visible: true, timeout: 5_000 }),
  );
  await retryClickUntil(
    async () => (await page.waitForSelector('button[aria-label="Confirm submission location"]', { visible: true })).click(),
    () => waitForVisibleText(page, "Selected:", 5_000),
  );
  await (await page.waitForSelector('input[type="file"]')).uploadFile(filePath);
  await page.waitForFunction(() => document.querySelectorAll(".file-list li span").length === 1);
  await retryClickUntil(
    () => page.click("#submission-consent"),
    () => page.waitForFunction(() => !document.querySelector('button[form="m3-submission-form"]')?.disabled, { timeout: 5_000 }),
  );
  await retryClickUntil(
    () => page.click('button[form="m3-submission-form"]'),
    () => page.waitForSelector("[data-submission-phase]", { visible: true, timeout: 5_000 }),
  );
  await page.waitForFunction(
    () => ["pending", "failed"].includes(document.querySelector("[data-submission-phase]")?.getAttribute("data-submission-phase")),
    { timeout: 90_000 },
  );
  const status = await page.$eval("[data-submission-phase]", (element) => ({
    phase: element.getAttribute("data-submission-phase"),
    text: element.textContent?.trim(),
  }));
  assert.equal(status.phase, "pending", `${name} failed: ${status.text}`);
  assert.match(status.text, /Submission \S+ is pending review\./);
  await retryClickUntil(
    () => clickVisibleByExactText(page, "[data-submission-phase] button", "Dismiss"),
    () => page.waitForSelector("[data-submission-phase]", { hidden: true, timeout: 5_000 }),
  );
}

async function graphql(query, variables, token) {
  const response = await fetch(`${baseUrl}/api/smokemap/graphql`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ query, variables }),
  });
  assert.equal(response.status, 200, `GraphQL returned HTTP ${response.status}`);
  const body = await response.json();
  assert.deepEqual(body.errors, undefined, `GraphQL failed: ${JSON.stringify(body.errors)}`);
  return body.data;
}

async function accessToken(email) {
  const data = await graphql(
    `mutation Login($email: String!, $password: String!) {
      tokenAuth(email: $email, password: $password) { token }
    }`,
    { email, password },
  );
  assert.ok(data.tokenAuth?.token, `no access token returned for ${email}`);
  return data.tokenAuth.token;
}

async function pendingIds(adminToken) {
  const data = await graphql(
    `query Queue { moderationQueueV4(first: 50) { items { id name } } }`,
    {},
    adminToken,
  );
  const ids = new Map(data.moderationQueueV4.items.map((item) => [item.name, item.id]));
  for (const name of fixtureNames) assert.ok(ids.has(name), `${name} was absent from moderation queue`);
  return ids;
}

async function runCreate(browser) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 900, deviceScaleFactor: 1 });
  const directUploads = [];
  const unexpected = [];
  await page.setRequestInterception(true);
  page.on("request", (request) => {
    const url = request.url();
    if (url.startsWith(baseUrl) || url.startsWith(basemapOrigin) || url.startsWith("data:") || url.startsWith("blob:")) {
      void request.continue();
    } else if (url.startsWith(storageOrigin)) {
      if (request.method() === "POST") directUploads.push(url);
      void request.continue();
    } else {
      unexpected.push(url);
      void request.abort("blockedbyclient");
    }
  });
  await signIn(page, ownerEmail, "/");
  assert.equal(await page.evaluate(() => window.isSecureContext), true, "submission origin is not secure");
  await page.waitForFunction(() => Array.from(document.querySelectorAll("button")).some((button) => button.textContent?.trim() === "+"), { timeout: 30_000 });
  const images = writeFixtureImages();
  for (let index = 0; index < fixtureNames.length; index += 1) {
    await fillSubmission(page, fixtureNames[index], images[index]);
    console.log(`ok - browser created pending media submission: ${fixtureNames[index]}`);
  }
  assert.equal(directUploads.length, fixtureNames.length, "each submission did not perform one real MinIO upload");
  assert.deepEqual(unexpected, [], "creation browser attempted an external request");
  console.log("ok - all lifecycle fixtures used real presigned direct-to-MinIO uploads");
}

async function clickApproveFor(page, name) {
  await page.waitForFunction(
    (expected) => Array.from(document.querySelectorAll("*")).some((element) => element.textContent?.trim() === expected),
    { timeout: 30_000 },
    name,
  );
  const clicked = await page.evaluate((expected) => {
    const title = Array.from(document.querySelectorAll("*")).find((element) => element.textContent?.trim() === expected);
    let current = title;
    while (current) {
      const approve = Array.from(current.querySelectorAll("button")).find((button) => button.textContent?.trim() === "Approve");
      if (approve) {
        approve.click();
        return true;
      }
      current = current.parentElement;
    }
    return false;
  }, name);
  assert.equal(clicked, true, `could not find approval control for ${name}`);
}

async function runLifecycle(browser) {
  const adminToken = await accessToken(adminEmail);
  const ownerToken = await accessToken(ownerEmail);
  const ids = await pendingIds(adminToken);

  const moderatorPage = await browser.newPage();
  await moderatorPage.setViewport({ width: 1280, height: 900, deviceScaleFactor: 1 });
  await signIn(moderatorPage, adminEmail, "/requests");
  await waitForVisibleText(moderatorPage, "Moderation queue", 30_000);
  await clickApproveFor(moderatorPage, approvedName);
  await moderatorPage.waitForSelector('textarea[aria-label="Review comment"]', { visible: true });
  await moderatorPage.type('textarea[aria-label="Review comment"]', "Approved by the public media E2E.");
  await clickVisibleByExactText(moderatorPage, "button", "Confirm approval");
  await waitForVisibleText(moderatorPage, "Submission approved and published to the map.", 90_000);
  console.log("ok - real moderation UI approved and published the media submission");

  const rejected = await graphql(
    `mutation Reject($id: ID!, $key: String!) {
      rejectSubmissionV4(submissionId: $id, idempotencyKey: $key, input: {comment: "Rejected by the public media E2E."}) {
        submission { id state } replayed
      }
    }`,
    { id: ids.get(rejectedName), key: "issue-100-reject-media" },
    adminToken,
  );
  assert.equal(rejected.rejectSubmissionV4.submission.state, "rejected");
  const withdrawn = await graphql(
    `mutation Withdraw($id: ID!, $key: String!) {
      withdrawSubmissionV4(submissionId: $id, idempotencyKey: $key) {
        submission { id state } replayed
      }
    }`,
    { id: ids.get(withdrawnName), key: "issue-100-withdraw-media" },
    ownerToken,
  );
  assert.equal(withdrawn.withdrawSubmissionV4.submission.state, "withdrawn");
  console.log("ok - supported backend lifecycle APIs rejected and withdrew distinct browser submissions");

  const context = await browser.createBrowserContext();
  const page = await context.newPage();
  await page.setViewport({ width: 1280, height: 900, deviceScaleFactor: 1 });
  const unexpected = [];
  const networkUrls = [];
  const publicPayloads = [];
  const responseReads = [];
  await page.setRequestInterception(true);
  page.on("request", (request) => {
    const url = request.url();
    if (url.startsWith(baseUrl) || url.startsWith(basemapOrigin) || url.startsWith("data:") || url.startsWith("blob:")) {
      if (url.includes("/api/")) networkUrls.push(url);
      void request.continue();
    } else {
      unexpected.push(url);
      void request.abort("blockedbyclient");
    }
  });
  page.on("response", (response) => {
    const url = response.url();
    if (!url.startsWith(baseUrl) || !url.includes("/api/")) return;
    const contentType = response.headers()["content-type"] ?? "";
    if (contentType.includes("json")) {
      responseReads.push(
        response.json().then((body) => publicPayloads.push({ url, status: response.status(), body })),
      );
    } else if (url.includes("/api/v1/media/")) {
      publicPayloads.push({ url, status: response.status(), contentType });
    }
  });

  const viewportResponsePromise = page.waitForResponse(
    (response) => response.url().includes("/api/smokemap/locations") && response.status() === 200,
    { timeout: 30_000 },
  );
  await page.goto(baseUrl, { waitUntil: "domcontentloaded", timeout: 30_000 });
  const viewportBody = await (await viewportResponsePromise).json();
  const viewportNames = viewportBody.features.map((feature) => feature.properties?.name);
  assert.ok(viewportNames.includes(approvedName), "approved Place was absent from the public map viewport");
  assert.ok(!viewportNames.includes(rejectedName), "rejected submission appeared on the public map");
  assert.ok(!viewportNames.includes(withdrawnName), "withdrawn submission appeared on the public map");

  const search = await page.waitForSelector('input[placeholder="Find a place"]', { visible: true });
  await search.type(approvedName);
  await page.waitForFunction(
    (expected) => Array.from(document.querySelectorAll('[role="option"]')).some((element) => element.textContent?.includes(expected)),
    { timeout: 30_000 },
    approvedName,
  );
  const placeResponsePromise = page.waitForResponse(
    (response) =>
      response.url().includes("/api/smokemap/graphql") &&
      response.request().method() === "POST" &&
      response.request().postData()?.includes("GetPlaceById"),
    { timeout: 30_000 },
  );
  const mediaResponsePromise = page
    .waitForResponse(
      (response) => response.url().includes("/api/v1/media/"),
      { timeout: 30_000 },
    )
    .catch((error) => error);
  await page.keyboard.press("Enter");
  const placePayload = await (await placeResponsePromise).json();
  const approvedMedia = placePayload.data?.placeById?.media;
  assert.equal(approvedMedia?.length, 1, "public place detail did not expose one approved rendition");
  const mediaUrl = new URL(approvedMedia[0].url, baseUrl);
  assert.equal(
    mediaUrl.origin,
    new URL(baseUrl).origin,
    `public media URL escaped the application origin: ${mediaUrl.origin}`,
  );
  assert.match(mediaUrl.pathname, /^\/api\/v1\/media\/[0-9a-f-]+\/$/i);
  const mediaResponse = await mediaResponsePromise;
  if (mediaResponse instanceof Error) throw mediaResponse;
  assert.equal(mediaResponse.url(), mediaUrl.toString(), "browser requested a different media URL");
  assert.equal(mediaResponse.status(), 200, `approved rendition returned HTTP ${mediaResponse.status()}`);
  assert.match(mediaResponse.headers()["content-type"] ?? "", /^image\//);
  const imageSelector = `img[alt="${approvedName} view 1"]`;
  await page.waitForFunction(
    (selector) => {
      const image = document.querySelector(selector);
      return image?.complete && image.naturalWidth > 0;
    },
    { timeout: 30_000 },
    imageSelector,
  );
  const dialogHtml = await page.$eval('[role="dialog"]', (element) => element.outerHTML);

  for (const name of [rejectedName, withdrawnName]) {
    const result = await page.evaluate(async (query) => {
      const response = await fetch(`/api/smokemap/places/search?q=${encodeURIComponent(query)}&limit=20`);
      return response.json();
    }, name);
    assert.equal(result.results.some((item) => item.name === name), false, `${name} became public`);
  }
  await page.waitForNetworkIdle({ idleTime: 500, timeout: 15_000 });
  await Promise.all(responseReads);
  assert.deepEqual(unexpected, [], "anonymous browser attempted an external request");
  const cookies = await page.cookies();
  const authenticatedCookieNames = cookies
    .map((cookie) => cookie.name)
    .filter((name) => name.includes("next-auth") || name.includes("session-token"));
  assert.deepEqual(authenticatedCookieNames, [], "anonymous proof carried an authentication cookie");

  mkdirSync(stateDir, { recursive: true });
  writeFileSync(
    join(stateDir, "public-observation.json"),
    JSON.stringify({
      approvedName,
      viewportNames,
      imageRendered: true,
      authenticatedCookieNames,
      networkUrls,
      publicPayloads,
      dialogHtml,
    }),
  );
  await context.close();
  console.log("ok - anonymous public map/search opened the Place and rendered its approved rendition");
}

let browser;
let basemapServer;
try {
  basemapServer = await startBasemapServer();
  browser = await puppeteer.launch({
    headless: true,
    args: [
      "--disable-setuid-sandbox",
      "--enable-unsafe-swiftshader",
      "--no-sandbox",
      "--use-angle=swiftshader",
      `--unsafely-treat-insecure-origin-as-secure=${baseUrl}`,
    ],
  });
  if (phase === "create") await runCreate(browser);
  else await runLifecycle(browser);
} finally {
  await browser?.close();
  if (basemapServer) await new Promise((resolve) => basemapServer.close(resolve));
}
