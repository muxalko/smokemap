import { warmFrontend } from "./frontend-readiness.mjs";

await warmFrontend(process.env.E2E_BASE_URL ?? "http://frontend:3000");
console.log("ok - development homepage compiled before browser E2E startup");
await import(new URL(`../${process.argv[2]}`, import.meta.url));
