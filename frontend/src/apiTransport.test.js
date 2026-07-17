import assert from "node:assert/strict";
import test from "node:test";

import { createApiRequester } from "./apiTransport.js";


test("browser mode preserves the existing HTTP fetch transport", async () => {
  const calls = [];
  const request = createApiRequester({
    isTauriImpl: () => false,
    baseUrl: "http://127.0.0.1:8000",
    fetchImpl: async (url, options) => {
      calls.push({ url, options });
      return response(200, { status: "ok" });
    },
    invokeImpl: async () => assert.fail("Tauri invoke must not run in browser mode"),
  });

  assert.deepEqual(await request("/api/health"), { status: "ok" });
  assert.equal(calls[0].url, "http://127.0.0.1:8000/api/health");
  assert.equal(calls[0].options.method, "GET");
});


test("Tauri mode sends only bounded API request data to the custom bridge", async () => {
  const calls = [];
  const request = createApiRequester({
    isTauriImpl: () => true,
    fetchImpl: async () => assert.fail("fetch must not run in Tauri mode"),
    invokeImpl: async (command, arguments_) => {
      calls.push({ command, arguments_ });
      return { status: 201, body: { created: true } };
    },
  });

  const data = await request("/api/projects", {
    method: "post",
    body: { project_name: "Example" },
  });
  assert.deepEqual(data, { created: true });
  assert.deepEqual(calls, [{
    command: "api_request",
    arguments_: {
      path: "/api/projects",
      method: "POST",
      body: { project_name: "Example" },
    },
  }]);
  assert.equal(JSON.stringify(calls).includes("127.0.0.1"), false);
  assert.equal(JSON.stringify(calls).toLowerCase().includes("token"), false);
});


test("browser and Tauri transports preserve backend detail errors", async () => {
  const browserRequest = createApiRequester({
    isTauriImpl: () => false,
    fetchImpl: async () => response(409, { detail: "Browser conflict." }),
  });
  const tauriRequest = createApiRequester({
    isTauriImpl: () => true,
    invokeImpl: async () => ({ status: 422, body: { detail: "Desktop validation." } }),
  });

  await assert.rejects(browserRequest("/api/projects"), /Browser conflict\./);
  await assert.rejects(tauriRequest("/api/projects"), /Desktop validation\./);
});


test("Tauri bridge rejections and aborts are normalized as errors", async () => {
  const rejected = createApiRequester({
    isTauriImpl: () => true,
    invokeImpl: async () => Promise.reject("Bridge rejected the request."),
  });
  await assert.rejects(rejected("/api/health"), /Bridge rejected the request\./);

  const controller = new AbortController();
  controller.abort();
  const aborted = createApiRequester({
    isTauriImpl: () => true,
    invokeImpl: async () => ({ status: 200, body: {} }),
  });
  await assert.rejects(aborted("/api/health", { signal: controller.signal }), { name: "AbortError" });
});


function response(status, body) {
  return {
    status,
    json: async () => body,
  };
}
