import assert from "node:assert/strict";
import { createServer } from "node:http";

import puppeteer from "puppeteer";

const baseUrl = process.env.E2E_BASE_URL ?? "http://frontend:3000";
const basemapOrigin = "http://127.0.0.1:4173";
const placeA = {
  name: "Smokemap E2E Issue 52 Region A",
  longitude: -77.01215461524441,
  latitude: 38.89630256339336,
};
const placeB = {
  name: "Smokemap E2E Issue 52 Region B",
  longitude: -76.86715461524441,
  latitude: 38.89630256339336,
};

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

function viewportFrom(responseUrl) {
  const rawBounds = new URL(responseUrl).searchParams.get("bbox");
  assert.ok(rawBounds, `viewport response omitted bbox: ${responseUrl}`);
  const bounds = rawBounds.split(",").map(Number);
  assert.equal(bounds.length, 4, `invalid response bbox: ${rawBounds}`);
  assert.ok(bounds.every(Number.isFinite), `non-finite response bbox: ${rawBounds}`);
  return {
    west: bounds[0],
    south: bounds[1],
    east: bounds[2],
    north: bounds[3],
  };
}

function responseNames(collection) {
  assert.equal(collection.type, "FeatureCollection");
  assert.ok(Array.isArray(collection.features));
  return collection.features.map((feature) => feature.properties?.name);
}

function isViewportResponse(response) {
  const url = new URL(response.url());
  return (
    url.origin === new URL(baseUrl).origin &&
    url.pathname === "/api/smokemap/locations" &&
    url.searchParams.has("bbox")
  );
}

function mercatorY(latitude) {
  const radians = (latitude * Math.PI) / 180;
  return Math.log(Math.tan(Math.PI / 4 + radians / 2));
}

function pointOnCanvas(canvas, viewport, place) {
  const xRatio =
    (place.longitude - viewport.west) / (viewport.east - viewport.west);
  const northY = mercatorY(viewport.north);
  const southY = mercatorY(viewport.south);
  const yRatio =
    (northY - mercatorY(place.latitude)) / (northY - southY);
  assert.ok(xRatio > 0 && xRatio < 1, `${place.name} is outside longitude bounds`);
  assert.ok(yRatio > 0 && yRatio < 1, `${place.name} is outside latitude bounds`);
  return {
    x: canvas.x + canvas.width * xRatio,
    y: canvas.y + canvas.height * yRatio,
  };
}

async function waitForVisibleText(page, text) {
  await page.waitForFunction(
    (expected) =>
      [...document.querySelectorAll("*")].some((element) => {
        const bounds = element.getBoundingClientRect();
        return (
          element.children.length === 0 &&
          element.textContent?.trim() === expected &&
          bounds.width > 0 &&
          bounds.height > 0
        );
      }),
    { timeout: 15_000 },
    text,
  );
}

async function waitForHiddenText(page, text) {
  await page.waitForFunction(
    (expected) =>
      ![...document.querySelectorAll("*")].some((element) => {
        const bounds = element.getBoundingClientRect();
        return (
          element.children.length === 0 &&
          element.textContent?.trim() === expected &&
          bounds.width > 0 &&
          bounds.height > 0
        );
      }),
    { timeout: 15_000 },
    text,
  );
}

async function waitForMapRender(page) {
  await page.waitForFunction(
    () =>
      ![...document.querySelectorAll('[role="status"]')].some((element) =>
        /^(Loading|Refreshing) places/.test(element.textContent?.trim() ?? ""),
      ),
    { timeout: 15_000 },
  );
  await page.evaluate(
    () =>
      new Promise((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(resolve)),
      ),
  );
}

async function closePlaceDialog(page) {
  const closed = await page.evaluate(() => {
    const closeButtons = [...document.querySelectorAll("button")].filter(
      (button) =>
        button.textContent?.trim() === "Close" &&
        button.getBoundingClientRect().width > 0,
    );
    closeButtons.at(-1)?.click();
    return closeButtons.length > 0;
  });
  assert.equal(closed, true, "place dialog did not expose a Close button");
}

async function dragMapAndWait(page, canvas, previousUrl, deltaX) {
  const responsePromise = page.waitForResponse(
    (response) =>
      isViewportResponse(response) &&
      response.url() !== previousUrl &&
      response.status() === 200,
    { timeout: 15_000 },
  );
  assert.ok(
    Math.abs(deltaX) <= canvas.width * 0.65,
    "drag distance exceeds the safe canvas span",
  );
  const startX =
    canvas.x + canvas.width * (deltaX < 0 ? 0.82 : 0.18);
  const endX = startX + deltaX;
  const y = canvas.y + canvas.height * 0.5;
  await page.mouse.move(startX, y);
  await page.mouse.down();
  for (let step = 1; step <= 20; step += 1) {
    const x = startX + ((endX - startX) * step) / 20;
    await page.mouse.move(x, y);
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  await page.mouse.up();
  return responsePromise;
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
    ],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 720, deviceScaleFactor: 1 });

  const unexpectedRequests = [];
  await page.setRequestInterception(true);
  page.on("request", (request) => {
    const url = request.url();
    if (url.startsWith(`${baseUrl}/`) || url.startsWith(`${basemapOrigin}/`)) {
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

  const initialResponsePromise = page.waitForResponse(
    (response) => isViewportResponse(response) && response.status() === 200,
    { timeout: 30_000 },
  );
  await page.goto(baseUrl, { waitUntil: "domcontentloaded", timeout: 30_000 });
  const initialResponse = await initialResponsePromise;
  const initialCollection = await initialResponse.json();
  const initialNames = responseNames(initialCollection);
  assert.ok(initialNames.includes(placeA.name), "initial viewport did not return A");
  assert.ok(!initialNames.includes(placeB.name), "initial viewport unexpectedly returned B");

  const canvasElement = await page.waitForSelector(".maplibregl-canvas", {
    visible: true,
    timeout: 15_000,
  });
  const canvas = await canvasElement.boundingBox();
  assert.ok(canvas && canvas.width > 0 && canvas.height > 0, "MapLibre canvas has no size");

  const initialViewport = viewportFrom(initialResponse.url());
  await page.waitForNetworkIdle({ idleTime: 500, timeout: 15_000 });
  await waitForMapRender(page);
  const aPoint = pointOnCanvas(canvas, initialViewport, placeA);
  await page.mouse.click(aPoint.x, aPoint.y);
  await waitForVisibleText(page, placeA.name);
  console.log("ok - Region A was returned by Django and opened from the MapLibre marker");
  await closePlaceDialog(page);
  await waitForHiddenText(page, placeA.name);

  let finalResponse = initialResponse;
  let finalViewport = initialViewport;
  let dragCount = 0;
  while (
    dragCount < 4 &&
    !(
      finalViewport.west > initialViewport.east &&
      placeB.longitude > finalViewport.west &&
      placeB.longitude < finalViewport.east
    )
  ) {
    const longitudeSpan = finalViewport.east - finalViewport.west;
    const currentCenter = (finalViewport.west + finalViewport.east) / 2;
    const requestedDelta =
      (-(placeB.longitude - currentCenter) / longitudeSpan) * canvas.width;
    const maxDelta = canvas.width * 0.65;
    const deltaX = Math.max(-maxDelta, Math.min(maxDelta, requestedDelta));
    finalResponse = await dragMapAndWait(
      page,
      canvas,
      finalResponse.url(),
      deltaX,
    );
    finalViewport = viewportFrom(finalResponse.url());
    dragCount += 1;
  }
  assert.ok(dragCount > 0, "test did not exercise a pointer drag");
  const finalCollection = await finalResponse.json();
  const finalNames = responseNames(finalCollection);
  assert.ok(finalNames.includes(placeB.name), "panned viewport did not return B");
  assert.ok(!finalNames.includes(placeA.name), "panned viewport retained stale A");

  assert.ok(
    finalViewport.west > initialViewport.east,
    `pointer drags did not reach a disjoint viewport: ${JSON.stringify({ initialViewport, finalViewport })}`,
  );
  assert.ok(
    placeA.longitude < finalViewport.west || placeA.longitude > finalViewport.east,
    "Region A remains inside the final viewport",
  );

  await waitForMapRender(page);
  const bPoint = pointOnCanvas(canvas, finalViewport, placeB);
  await page.mouse.click(bPoint.x, bPoint.y);
  await waitForVisibleText(page, placeB.name);
  console.log("ok - actual pointer drags reached a disjoint viewport where B opened and A was absent");

  assert.deepEqual(unexpectedRequests, [], "browser attempted external network requests");
  console.log("ok - deterministic local basemap served all map assets without external traffic");
} finally {
  await browser?.close();
  if (basemapServer) {
    await new Promise((resolve) => basemapServer.close(resolve));
  }
}
