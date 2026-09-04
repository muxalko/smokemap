import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { deflateSync } from "node:zlib";

import puppeteer from "puppeteer";

const baseUrl = process.env.E2E_BASE_URL ?? "http://frontend:3000";
const basemapOrigin = "http://127.0.0.1:4173";
const storageOrigin = "http://storage:9000";

// Matches the deterministic local test cohort provisioned by the real
// `provision_local_test_users` development-only Django command; this fallback
// mirrors that command's own documented default so the two stay in lockstep
// without either side reading the other's source.
const ownerEmail = "user-one@smokemap.local";
const ownerPassword =
  process.env.SMOKEMAP_LOCAL_TEST_PASSWORD ?? "Smokemap-local-test-only-2026!";

// Reuses the map's fixed initial center so the browser never has to pan to a
// deterministic point; distinct from Region A/B (issue #52) because these are
// private M3 submissions (`Request` rows), not public `Place` fixtures, and
// name-based duplicate detection means sharing a point is not a collision.
const submissionLongitude = -77.01215461524441;
const submissionLatitude = 38.89630256339336;
const categoryDisplayName = "Outdoors";

const zeroImagePlaceName = "Smokemap E2E Issue 77 Zero Image Place";
const multiImagePlaceName = "Smokemap E2E Issue 77 Multi Image Place";
const multiImageFileCount = 2;

const basemapStyle = JSON.stringify({
  version: 8,
  name: "Smokemap deterministic E2E basemap",
  glyphs: `${basemapOrigin}/fonts/{fontstack}/{range}.pbf`,
  sources: {},
  layers: [
    {
      id: "background",
      type: "background",
      paint: { "background-color": "#e5e7eb" },
    },
  ],
});

function startBasemapServer() {
  const server = createServer((request, response) => {
    if (request.url?.startsWith("/fonts/") && request.url.endsWith(".pbf")) {
      response.writeHead(200, {
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "no-store",
        "Content-Type": "application/x-protobuf",
      });
      response.end(Buffer.alloc(0));
      return;
    }
    if (request.url !== "/style.json") {
      response.writeHead(404).end();
      return;
    }
    response.writeHead(200, {
      "Access-Control-Allow-Origin": "*",
      "Cache-Control": "no-store",
      "Content-Type": "application/json",
    });
    response.end(basemapStyle);
  });
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(4173, "127.0.0.1", () => resolve(server));
  });
}

// --- Minimal, dependency-free PNG encoding -------------------------------
// Generates small, genuinely valid, distinct-content PNGs at run time so no
// binary fixtures are committed to the repository. Each image decodes for
// real through the backend's Pillow-based verification.

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
  for (const byte of buffer) {
    crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  }
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

function solidColorPng(width, height, [red, green, blue]) {
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  const ihdrData = Buffer.alloc(13);
  ihdrData.writeUInt32BE(width, 0);
  ihdrData.writeUInt32BE(height, 4);
  ihdrData[8] = 8; // bit depth
  ihdrData[9] = 2; // color type: truecolor (RGB)
  ihdrData[10] = 0; // compression
  ihdrData[11] = 0; // filter
  ihdrData[12] = 0; // interlace
  const ihdr = pngChunk("IHDR", ihdrData);

  const row = Buffer.alloc(1 + width * 3);
  for (let x = 0; x < width; x += 1) {
    row[1 + x * 3] = red;
    row[1 + x * 3 + 1] = green;
    row[1 + x * 3 + 2] = blue;
  }
  const raw = Buffer.concat(Array.from({ length: height }, () => row));
  const idat = pngChunk("IDAT", deflateSync(raw));
  const iend = pngChunk("IEND", Buffer.alloc(0));
  return Buffer.concat([signature, ihdr, idat, iend]);
}

function writeFixtureImages() {
  const directory = mkdtempSync(join(tmpdir(), "smokemap-e2e-media-"));
  const paths = [
    ["image-a.png", [220, 20, 60]],
    ["image-b.png", [30, 144, 255]],
    ["image-c.png", [34, 139, 34]],
  ]
    .slice(0, multiImageFileCount)
    .map(([filename, color]) => {
      const filePath = join(directory, filename);
      writeFileSync(filePath, solidColorPng(8, 8, color));
      return filePath;
    });
  assert.equal(paths.length, multiImageFileCount);
  return paths;
}

// --- Small DOM helpers, mirroring the style of e2e/viewport-pan.mjs -------

async function findVisibleByExactText(page, selector, text) {
  return page.evaluateHandle(
    (sel, expected) => {
      const candidates = Array.from(document.querySelectorAll(sel));
      return (
        candidates.find((element) => {
          const bounds = element.getBoundingClientRect();
          return (
            element.textContent?.trim() === expected &&
            bounds.width > 0 &&
            bounds.height > 0
          );
        }) ?? null
      );
    },
    selector,
    text,
  );
}

async function clickVisibleByExactText(page, selector, text, { timeout = 15_000 } = {}) {
  await page.waitForFunction(
    (sel, expected) =>
      Array.from(document.querySelectorAll(sel)).some((element) => {
        const bounds = element.getBoundingClientRect();
        return (
          element.textContent?.trim() === expected &&
          bounds.width > 0 &&
          bounds.height > 0
        );
      }),
    { timeout },
    selector,
    text,
  );
  const handle = await findVisibleByExactText(page, selector, text);
  const element = handle.asElement();
  assert.ok(element, `no visible "${selector}" matched exact text: ${text}`);
  await element.click();
  await handle.dispose();
}

async function waitForVisibleText(page, text, { timeout = 15_000 } = {}) {
  await page.waitForFunction(
    (expected) =>
      Array.from(document.querySelectorAll("*")).some((element) => {
        const bounds = element.getBoundingClientRect();
        return (
          element.textContent?.trim().includes(expected) &&
          bounds.width > 0 &&
          bounds.height > 0
        );
      }),
    { timeout },
    text,
  );
}

// A click landing between server-rendered markup and React finishing
// hydration attaches to no listener and is silently lost. This is only ever
// observed on the very first interaction after a full page navigation, so
// rather than guess at a fixed hydration delay, retry the click itself until
// its expected effect is observed.
async function retryClickUntil(clickAction, expectAction, { attempts = 4, timeout = 5_000 } = {}) {
  let lastError;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    await clickAction();
    try {
      await expectAction(timeout);
      return;
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError;
}

function submissionPhaseSelector() {
  return '[data-submission-phase]';
}

async function currentSubmissionPhase(page) {
  return page.evaluate(
    (sel) => document.querySelector(sel)?.getAttribute("data-submission-phase") ?? null,
    submissionPhaseSelector(),
  );
}

async function waitForSubmissionPhase(page, expectedPhases, { timeout = 60_000 } = {}) {
  await page.waitForFunction(
    (sel, expected) => {
      const phase = document.querySelector(sel)?.getAttribute("data-submission-phase");
      return Boolean(phase) && expected.includes(phase);
    },
    { timeout },
    submissionPhaseSelector(),
    expectedPhases,
  );
  return currentSubmissionPhase(page);
}

async function submissionStatusText(page) {
  return page.evaluate(
    (sel) => document.querySelector(sel)?.textContent?.trim() ?? "",
    submissionPhaseSelector(),
  );
}

async function assertSubmissionSucceeds(page, label, { timeout } = {}) {
  const phase = await waitForSubmissionPhase(page, ["pending", "failed"], { timeout });
  if (phase === "failed") {
    const message = await submissionStatusText(page);
    throw new Error(`${label}: submission failed instead of reaching pending: ${message}`);
  }
  const text = await submissionStatusText(page);
  const match = text.match(/Submission (\S+) is pending review\./);
  assert.ok(match, `${label}: pending banner did not contain a submission id: ${text}`);
  return match[1];
}

async function dismissSubmissionStatus(page) {
  // Same real-browser render race as the other retried clicks above: an
  // occasional click on a just-updated status banner attaches to no
  // listener, so retry the click itself rather than assume this one is
  // exempt.
  await retryClickUntil(
    () => clickVisibleByExactText(page, `${submissionPhaseSelector()} button`, "Dismiss"),
    (timeout) =>
      page.waitForFunction(
        (sel) => document.querySelector(sel) === null,
        { timeout },
        submissionPhaseSelector(),
      ),
  );
}

async function fillSubmissionBasics(page, name) {
  const nameInput = await page.waitForSelector('input[placeholder="Place name"]', {
    visible: true,
    timeout: 15_000,
  });
  await nameInput.click({ clickCount: 3 });
  await nameInput.type(name);

  // Opens the trigger unconditionally rather than matching its placeholder
  // text: a still-open frontend defect (request-react-form.tsx's post-submit
  // `form.reset(emptyForm)` omits `categorySlug`) leaves the previous
  // submission's category label on this button instead of resetting it to
  // "Select category", which would otherwise make the second submission's
  // basics never match here. Selecting explicitly still exercises the real
  // control and always yields the intended category regardless.
  await retryClickUntil(
    async () => {
      const categoryTrigger = await page.waitForSelector('button[role="combobox"]', {
        visible: true,
        timeout: 15_000,
      });
      await categoryTrigger.click();
    },
    (timeout) => page.waitForSelector("[cmdk-item]", { visible: true, timeout }),
  );
  await retryClickUntil(
    () => clickVisibleByExactText(page, "[cmdk-item]", categoryDisplayName),
    (timeout) => page.waitForSelector("[cmdk-item]", { hidden: true, timeout }),
  );
}

async function chooseFixedMapLocation(page) {
  if (process.env.E2E_DEBUG) {
    writeFileSync("/tmp/e2e-debug-before-location.html", await page.content());
    await page.screenshot({ path: "/tmp/e2e-debug-before-location.png" });
  }
  // A dialog's first click can land before its own just-mounted content
  // finishes attaching listeners, the same class of race documented on the
  // very first post-navigation click above; retry it the same way rather
  // than assume this one dialog is exempt.
  await retryClickUntil(
    () => clickVisibleByExactText(page, "button", "Choose location on map"),
    (timeout) =>
      page.waitForSelector('button[aria-label="Confirm submission location"]', {
        visible: true,
        timeout,
      }),
  );
  await retryClickUntil(
    async () => {
      const confirmButton = await page.waitForSelector(
        'button[aria-label="Confirm submission location"]',
        { visible: true, timeout: 15_000 },
      );
      await confirmButton.click();
    },
    (timeout) => waitForVisibleText(page, "Selected:", { timeout }),
  );
}

async function attachImages(page, filePaths) {
  const input = await page.waitForSelector('input[type="file"]', { timeout: 10_000 });
  await input.uploadFile(...filePaths);
  await page.waitForFunction(
    (expected) =>
      Array.from(document.querySelectorAll(".file-list li span")).filter(
        (span) => span.textContent && span.textContent.length > 0,
      ).length === expected,
    { timeout: 10_000 },
    filePaths.length,
  );
}

async function acceptConsentAndSubmit(page) {
  await retryClickUntil(
    () => page.click("#submission-consent"),
    (timeout) =>
      page.waitForFunction(
        () => {
          const button = document.querySelector('button[form="m3-submission-form"]');
          return Boolean(button) && !button.disabled;
        },
        { timeout },
      ),
  );
  await retryClickUntil(
    () => page.click('button[form="m3-submission-form"]'),
    (timeout) => page.waitForSelector(submissionPhaseSelector(), { visible: true, timeout }),
  );
}

let browser;
let basemapServer;
let page;
try {
  basemapServer = await startBasemapServer();
  browser = await puppeteer.launch({
    headless: true,
    args: [
      "--disable-setuid-sandbox",
      "--enable-unsafe-swiftshader",
      "--no-sandbox",
      "--use-angle=swiftshader",
      // The browser must call crypto.subtle to hash each selected image, the
      // same client-side operation a real user's browser performs before
      // requesting a media upload intent. That API is gated behind a secure
      // context, and this plain-http E2E network intentionally has no TLS
      // termination in front of it, so this well-known Chromium test-only
      // switch marks the exact frontend origin as a secure context. It does
      // not stub, skip, or shortcut the hashing itself.
      `--unsafely-treat-insecure-origin-as-secure=${baseUrl}`,
    ],
  });
  page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 900, deviceScaleFactor: 1 });
  if (process.env.E2E_DEBUG) {
    page.on("console", (message) => console.log("BROWSER:", message.type(), message.text()));
    page.on("pageerror", (error) => console.log("BROWSER PAGE ERROR:", error));
  }

  const unexpectedRequests = [];
  const directUploadRequests = [];
  await page.setRequestInterception(true);
  page.on("request", (request) => {
    const url = request.url();
    if (
      url.startsWith(`${baseUrl}/`) ||
      url === baseUrl ||
      url.startsWith(`${basemapOrigin}/`)
    ) {
      void request.continue();
      return;
    }
    if (url.startsWith(`${storageOrigin}/`)) {
      if (request.method() === "POST") directUploadRequests.push(url);
      void request.continue();
      return;
    }
    if (url.startsWith("data:") || url.startsWith("blob:")) {
      void request.continue();
      return;
    }
    unexpectedRequests.push(url);
    void request.abort("blockedbyclient");
  });

  await page.goto(
    `${baseUrl}/api/auth/signin?callbackUrl=${encodeURIComponent(`${baseUrl}/`)}`,
    { waitUntil: "domcontentloaded", timeout: 30_000 },
  );
  assert.equal(
    await page.evaluate(() => window.isSecureContext),
    true,
    `${baseUrl} was not treated as a secure context; crypto.subtle would be unavailable for real client-side image hashing`,
  );

  const emailInput = await page.waitForSelector('input[name="email"]', {
    visible: true,
    timeout: 15_000,
  });
  await emailInput.type(ownerEmail);
  const passwordInput = await page.waitForSelector('input[name="password"]', {
    visible: true,
  });
  await passwordInput.type(ownerPassword);

  await Promise.all([
    page.waitForNavigation({ waitUntil: "domcontentloaded", timeout: 30_000 }),
    page.click('button[type="submit"]'),
  ]);

  await page.waitForFunction(
    () =>
      Array.from(document.querySelectorAll("button")).some(
        (button) => button.textContent?.trim() === "+" && !button.getAttribute("aria-label"),
      ),
    { timeout: 30_000 },
  );
  console.log("ok - real NextAuth credentials sign-in reached the authenticated submission UI");

  // --- Zero-image submission -------------------------------------------
  // The very first click after this full-page navigation can land before
  // React finishes hydrating, so retry it until the dialog actually opens.
  await retryClickUntil(
    () => clickVisibleByExactText(page, "button", "+"),
    (timeout) => waitForVisibleText(page, "Submit a place", { timeout }),
  );
  await fillSubmissionBasics(page, zeroImagePlaceName);
  await chooseFixedMapLocation(page);
  await acceptConsentAndSubmit(page);

  const zeroImageSubmissionId = await assertSubmissionSucceeds(page, "zero-image submission", {
    timeout: 30_000,
  });
  console.log(
    `ok - zero-image submission ${zeroImageSubmissionId} reported pending only after backend finalization`,
  );
  await dismissSubmissionStatus(page);

  // --- Multi-image submission --------------------------------------------
  const fixtureImagePaths = writeFixtureImages();

  await retryClickUntil(
    () => clickVisibleByExactText(page, "button", "+"),
    (timeout) => waitForVisibleText(page, "Submit a place", { timeout }),
  );
  await fillSubmissionBasics(page, multiImagePlaceName);
  await chooseFixedMapLocation(page);
  await attachImages(page, fixtureImagePaths);
  await acceptConsentAndSubmit(page);

  const multiImageSubmissionId = await assertSubmissionSucceeds(page, "multi-image submission", {
    timeout: 90_000,
  });
  console.log(
    `ok - multi-image (${fixtureImagePaths.length}-file) submission ${multiImageSubmissionId} reported pending only after backend finalization`,
  );

  assert.equal(
    directUploadRequests.length,
    fixtureImagePaths.length,
    `expected ${fixtureImagePaths.length} real direct-to-storage uploads, observed ${directUploadRequests.length}`,
  );
  for (const url of directUploadRequests) {
    assert.ok(
      url.startsWith(`${storageOrigin}/`),
      `direct upload did not target the private MinIO endpoint: ${url}`,
    );
  }
  console.log(
    `ok - browser performed ${directUploadRequests.length} real presigned direct-upload POST(s) to ${storageOrigin}`,
  );

  assert.deepEqual(unexpectedRequests, [], "browser attempted unexpected external network requests");
  console.log("ok - no unmocked network path was used outside the frontend, storage and local basemap origins");
} catch (error) {
  // Opt-in diagnostic aid, never used by CI: dumps the failing page's HTML
  // and a screenshot to help debug a local run without re-instrumenting.
  if (process.env.E2E_DEBUG && page) {
    try {
      writeFileSync("/tmp/e2e-debug.html", await page.content());
      await page.screenshot({ path: "/tmp/e2e-debug.png", fullPage: true });
    } catch {
      // Best-effort only; never mask the real failure below.
    }
  }
  throw error;
} finally {
  await browser?.close();
  if (basemapServer) {
    await new Promise((resolve) => basemapServer.close(resolve));
  }
}
