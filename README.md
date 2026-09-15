# Thumbnail Fix Overlay

Replace the matching files in the previous project and redeploy.

Changes:
- Adds `/api/thumbnail/{video_id}` to proxy YouTube thumbnails through the app/container.
- Tries maxres, sd, then hq JPEG thumbnails.
- Browser now loads the same-origin thumbnail endpoint first and falls back to yt-dlp's original URL.
