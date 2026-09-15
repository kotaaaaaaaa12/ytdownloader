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
  headers.set("Content-Security-Policy", "default-src 'self'; connect-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; script-src 'self'; base-uri 'none'; form-action 'self'");
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
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

  return Response.json({
    ok: false,
    error: "Container is temporarily unavailable in APAC.",
    detail: String(lastError?.message || lastError || "unknown error"),
    retryable: true
  }, { status: 503, headers: { "Retry-After": "10" } });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname.startsWith("/api/")) {
      const container = getContainer(env.DOWNLOADER, "main");
      return fetchContainerWithRetry(container, request);
    }

    return securityHeaders(await env.ASSETS.fetch(request));
  },
};
