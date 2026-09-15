# Cloudflare yt-dlp Downloader

A small Cloudflare Workers + Containers app for downloading media you own or have permission to save.

## Architecture

- Cloudflare Worker: serves the UI and proxies `/api/*` to the Container.
- Cloudflare Container: runs Python, yt-dlp, Deno and FFmpeg.
- One Container instance is used and sleeps after 10 minutes of inactivity.
- Files are temporary and disappear when the Container is replaced/restarted.

## Deploy from GitHub

1. Push this project to a GitHub repository.
2. In Cloudflare Dashboard, create/import a Worker from that repository.
3. Set the deploy command to:

   ```bash
   npx wrangler deploy
   ```

4. Use a Workers Paid plan because Cloudflare Containers require it.
5. Deploy. Wrangler builds the Dockerfile and Container image automatically.

The default Container type is `standard-2` (1 vCPU, 6 GiB RAM, 12 GB disk) because 4K FFmpeg conversion is CPU/RAM/disk intensive.

## Local deploy

```bash
npm install
npx wrangler deploy
```

A local Docker-compatible engine is required when deploying the local Dockerfile from your own machine. Cloudflare Workers Builds can perform the build when deploying from GitHub.

## Notes

YouTube may still challenge or block datacenter IP addresses. Moving yt-dlp from Colab to Cloudflare does not guarantee that YouTube will accept the Cloudflare Container egress IP. This project intentionally does not store account cookies or login credentials.

All finished downloads use only `.mp4` or `.mov`. Audio-only mode stores AAC audio inside the selected MP4/MOV container.

4K iOS-compatible mode converts 1440p/2160p video to HEVC (`hvc1`) with AAC. 1080p and lower use H.264 + AAC.
