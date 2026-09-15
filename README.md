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

## Progress and placement

- The progress bar now follows real yt-dlp download percentage and FFmpeg output time.
- Container placement is restricted to the Cloudflare `APAC` region.
- The container uses `standard-3` (2 vCPU / 8 GiB RAM / 16 GB disk) to speed up video encoding.
- 1440p/4K iOS-compatible output uses HEVC (`hvc1`) with FFmpeg `fast` preset.

## Smart iOS mode

When iOS Compatible is enabled, the downloader now prefers an H.264/HEVC source at the selected resolution. If the source is already H.264 or HEVC, FFmpeg copies the video stream and only prepares the final MP4/MOV and AAC audio. VP9/AV1 sources are transcoded only when necessary. VP9/AV1 fallback conversion now uses H.264 (`libx264`) with the `ultrafast` preset for maximum FFmpeg speed. This is faster than x265/HEVC but produces larger files. The container has no region constraint and uses `standard-4` (4 vCPU).

## YouTube PO Token / Chromium build

This build adds a current yt-dlp YouTube fallback stack:

- Chromium installed in the Container for browser-capable tooling/debugging.
- Deno installed as yt-dlp's JavaScript runtime.
- `bgutil-ytdlp-pot-provider` installed through pip.
- BgUtils provider source installed at `/opt/bgutil-ytdlp-pot-provider/server`.
- First extraction attempt uses `mweb` with the PO Token provider.
- If that fails, the API retries with `web_safari`, then yt-dlp's default client.
- `/api/health` reports whether Chromium and Deno are present.

This deliberately does **not** automate Google sign-in or persist Google/YouTube session cookies. If YouTube blocks a datacenter IP even with PO tokens, changing clients/tokens cannot guarantee access.


## Fast FFmpeg mode
This build removes the APAC placement constraint, restores `standard-4`, and uses H.264 `libx264 -preset ultrafast` whenever a VP9/AV1 source must be transcoded for iOS compatibility. Compatible H.264/HEVC sources are still stream-copied without re-encoding.
