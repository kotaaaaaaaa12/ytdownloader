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

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname.startsWith("/api/")) {
      const container = getContainer(env.DOWNLOADER, "main");
      return container.fetch(request);
    }

    return securityHeaders(await env.ASSETS.fetch(request));
  },
};
