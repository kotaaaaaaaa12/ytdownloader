import { Container, getContainer } from "@cloudflare/containers";

export class DownloaderContainer extends Container {
  defaultPort = 8080;
  sleepAfter = "10m";
  enableInternet = true;

  onStart() {
    console.log("Downloader container started");
  }

  onStop() {
    console.log("Downloader container stopped");
  }

  onError(error) {
    console.error("Downloader container error", error);
  }
}

function securityHeaders(response) {
  const headers = new Headers(response.headers);
  headers.set("X-Content-Type-Options", "nosniff");
  headers.set("Referrer-Policy", "no-referrer");
  headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  headers.set(
    "Content-Security-Policy",
    "default-src 'self'; connect-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; script-src 'self'; base-uri 'none'; form-action 'self'",
  );
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function apiResponse(body, init = {}) {
  const headers = new Headers(init.headers);
  headers.set("Cache-Control", "no-store");
  headers.set("Content-Type", "application/json; charset=utf-8");
  return securityHeaders(new Response(JSON.stringify(body), { ...init, headers }));
}

function isAllowedYouTubeUrl(rawUrl) {
  if (typeof rawUrl !== "string" || rawUrl.length > 4096) return false;

  try {
    const url = new URL(rawUrl);
    if (url.protocol !== "https:") return false;

    const host = url.hostname.toLowerCase();
    return host === "youtu.be" || host === "youtube.com" || host.endsWith(".youtube.com");
  } catch {
    return false;
  }
}

function routeKind(url, method) {
  const path = url.pathname;

  if (method === "GET" && path === "/api/health") return "health";
  if (method === "GET" && /^\/api\/thumbnail\/[A-Za-z0-9_-]{11}$/.test(path)) return "thumbnail";
  if (method === "POST" && path === "/api/info") return "info";
  if (method === "POST" && path === "/api/download") return "download";
  if (method === "GET" && /^\/api\/status\/[a-f0-9]{32}$/.test(path)) return "status";
  if (method === "GET" && /^\/api\/file\/[a-f0-9]{32}$/.test(path)) return "file";

  return null;
}

async function validateJsonRequest(request) {
  const contentType = request.headers.get("Content-Type") || "";
  if (!contentType.toLowerCase().startsWith("application/json")) {
    return {
      error: apiResponse(
        { ok: false, error: "Content-Type must be application/json." },
        { status: 415 },
      ),
    };
  }

  let rawBody;
  try {
    rawBody = await request.clone().text();
  } catch {
    return { error: apiResponse({ ok: false, error: "Unable to read request body." }, { status: 400 }) };
  }

  if (rawBody.length > 16 * 1024) {
    return { error: apiResponse({ ok: false, error: "Request body is too large." }, { status: 413 }) };
  }

  let body;
  try {
    body = JSON.parse(rawBody);
  } catch {
    return { error: apiResponse({ ok: false, error: "Request body must be valid JSON." }, { status: 400 }) };
  }

  if (!isAllowedYouTubeUrl(body?.url)) {
    return { error: apiResponse({ ok: false, error: "Only HTTPS YouTube URLs are accepted." }, { status: 400 }) };
  }

  return { body };
}

async function enforceRateLimit(request, env, kind) {
  const limiter = kind === "download" ? env.DOWNLOAD_RATE_LIMITER : env.INFO_RATE_LIMITER;
  if (!limiter) return null;

  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  const { success } = await limiter.limit({ key: `${kind}:${ip}` });
  if (success) return null;

  return apiResponse(
    { ok: false, error: "Too many requests. Try again shortly." },
    { status: 429, headers: { "Retry-After": "60" } },
  );
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function fetchContainerWithRetry(container, request) {
  const delays = [0, 500, 1000, 2000, 3000, 5000];
  let lastError;

  for (let attempt = 0; attempt < delays.length; attempt++) {
    if (delays[attempt]) await sleep(delays[attempt]);

    try {
      const response = await container.fetch(request.clone());
      if (response.status !== 503) return response;

      const text = await response.clone().text().catch(() => "");
      if (!/no container instance|try again later|container/i.test(text)) {
        return response;
      }
      lastError = new Error(text || `Container unavailable (${response.status})`);
    } catch (error) {
      lastError = error;
      const message = String(error?.message || error);
      if (!/no container instance|try again later|container/i.test(message)) {
        throw error;
      }
    }
  }

  console.error("Downloader container remained unavailable after retries", lastError);
  return apiResponse(
    {
      ok: false,
      error: "Downloader is temporarily unavailable.",
      retryable: true,
    },
    { status: 503, headers: { "Retry-After": "10" } },
  );
}

async function sanitizeApiResponse(kind, response) {
  if (kind === "health") {
    return apiResponse({ ok: response.ok }, { status: response.ok ? 200 : 503 });
  }

  if (kind === "status" && response.ok) {
    try {
      const body = await response.clone().json();
      if (body?.status === "error") {
        delete body.detail;
        body.error = "Download failed. Check server logs for details.";
        return apiResponse(body, { status: response.status });
      }
    } catch {
      // Preserve non-JSON responses below.
    }
  }

  if (response.status >= 500) {
    return apiResponse(
      { ok: false, error: "Request failed on the server." },
      { status: response.status },
    );
  }

  return securityHeaders(response);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname.startsWith("/api/")) {
      const kind = routeKind(url, request.method);
      if (!kind) {
        return apiResponse({ ok: false, error: "Not found." }, { status: 404 });
      }

      if (kind === "info" || kind === "download") {
        const validation = await validateJsonRequest(request);
        if (validation.error) return validation.error;

        const rateLimited = await enforceRateLimit(request, env, kind);
        if (rateLimited) return rateLimited;
      }

      const container = getContainer(env.DOWNLOADER, "main");
      const response = await fetchContainerWithRetry(container, request);
      return sanitizeApiResponse(kind, response);
    }

    return securityHeaders(await env.ASSETS.fetch(request));
  },
};
