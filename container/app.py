import asyncio
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, HttpUrl

app = FastAPI(docs_url=None, redoc_url=None)
ROOT = Path("/data/jobs")
ROOT.mkdir(parents=True, exist_ok=True)
JOBS: dict[str, dict] = {}
LOCK = threading.Lock()
MAX_AGE_SECONDS = 30 * 60


def cleanup_old_jobs():
    now = time.time()
    with LOCK:
        stale = [job_id for job_id, job in JOBS.items() if now - job.get("created", now) > MAX_AGE_SECONDS]
    for job_id in stale:
        path = ROOT / job_id
        shutil.rmtree(path, ignore_errors=True)
        with LOCK:
            JOBS.pop(job_id, None)


def run_json(cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=90)
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(message[-5000:])
    return json.loads(proc.stdout)


def base_ydl_args() -> list[str]:
    return [
        "yt-dlp",
        "--no-playlist",
        "--no-warnings",
        "--js-runtimes",
        "deno",
    ]


def sanitize_title(value: str) -> str:
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", value).strip()
    return value[:160] or "download"


class InfoRequest(BaseModel):
    url: HttpUrl


class DownloadRequest(BaseModel):
    url: HttpUrl
    mode: Literal["av", "video", "audio"] = "av"
    height: int | None = None
    container: Literal["mp4", "mov"] = "mp4"
    ios_compatible: bool = True


@app.get("/api/health")
def health():
    cleanup_old_jobs()
    return {"ok": True}


@app.post("/api/info")
def info(payload: InfoRequest):
    cleanup_old_jobs()
    cmd = base_ydl_args() + ["--dump-single-json", "--skip-download", str(payload.url)]
    try:
        data = run_json(cmd)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    formats = data.get("formats") or []
    heights = sorted({int(f["height"]) for f in formats if f.get("height") and f.get("vcodec") != "none"}, reverse=True)
    fps_by_height = {}
    for h in heights:
        fps = [float(f.get("fps") or 0) for f in formats if f.get("height") == h and f.get("vcodec") != "none"]
        fps_by_height[str(h)] = round(max(fps), 2) if fps else None

    return {
        "id": data.get("id"),
        "title": data.get("title"),
        "uploader": data.get("uploader"),
        "duration": data.get("duration"),
        "thumbnail": data.get("thumbnail"),
        "heights": heights,
        "fps": fps_by_height,
    }


def set_job(job_id: str, **updates):
    with LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(updates)


def find_final_source(workdir: Path) -> Path:
    candidates = [p for p in workdir.iterdir() if p.is_file() and not p.name.endswith((".part", ".ytdl"))]
    if not candidates:
        raise RuntimeError("Downloaded source file was not found")
    return max(candidates, key=lambda p: p.stat().st_size)


def ffprobe(path: Path) -> dict:
    return run_json([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate",
        "-of", "json", str(path),
    ])


def parse_percent(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)%", text)
    if not match:
        return None
    try:
        return max(0.0, min(100.0, float(match.group(1))))
    except ValueError:
        return None


def run_ytdlp_with_progress(job_id: str, args: list[str]):
    cmd = args[:-1] + [
        "--newline",
        "--progress-template", "download:%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
        args[-1],
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    tail: list[str] = []
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.strip()
        if not line:
            continue
        tail.append(line)
        tail = tail[-120:]
        if line.startswith("download:"):
            payload = line[len("download:"):]
            parts = payload.split("|")
            percent = parse_percent(parts[0])
            if percent is not None:
                speed = parts[1].strip() if len(parts) > 1 else ""
                eta = parts[2].strip() if len(parts) > 2 else ""
                details = " • ".join(x for x in (speed, f"ETA {eta}" if eta and eta != "NA" else "") if x and x != "NA")
                set_job(
                    job_id,
                    status="downloading",
                    progress=f"Downloading source — {percent:.1f}%",
                    stage_percent=percent,
                    percent=round(percent * 0.70, 1),
                    detail=details,
                )
    code = proc.wait()
    if code != 0:
        raise RuntimeError("\n".join(tail)[-7000:])


def run_ffmpeg_with_progress(job_id: str, cmd: list[str], duration: float, label: str):
    progress_cmd = cmd[:-1] + ["-progress", "pipe:1", "-nostats", cmd[-1]]
    proc = subprocess.Popen(
        progress_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    tail: list[str] = []
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.strip()
        if not line:
            continue
        tail.append(line)
        tail = tail[-160:]
        if line.startswith("out_time_ms=") or line.startswith("out_time_us="):
            try:
                value = int(line.split("=", 1)[1])
                seconds = value / 1_000_000
                stage = 0.0 if duration <= 0 else max(0.0, min(99.5, seconds / duration * 100))
                set_job(
                    job_id,
                    status="converting",
                    progress=f"{label} — {stage:.1f}%",
                    stage_percent=round(stage, 1),
                    percent=round(70 + stage * 0.29, 1),
                    detail=f"{seconds:.0f}s / {duration:.0f}s" if duration > 0 else "",
                )
            except (ValueError, ZeroDivisionError):
                pass
    code = proc.wait()
    if code != 0:
        raise RuntimeError("\n".join(tail)[-7000:])


def download_job(job_id: str, req: DownloadRequest):
    job_dir = ROOT / job_id
    workdir = job_dir / "work"
    workdir.mkdir(parents=True, exist_ok=True)
    set_job(job_id, status="downloading", progress="Starting download", stage_percent=0, percent=0, detail="")

    try:
        url = str(req.url)
        title_info = run_json(base_ydl_args() + ["--dump-single-json", "--skip-download", url])
        title = sanitize_title(title_info.get("title") or "download")

        output_template = str(workdir / "source.%(ext)s")
        args = base_ydl_args() + ["-o", output_template]

        if req.mode == "audio":
            args += ["-f", "bestaudio[acodec^=mp4a]/bestaudio/best", url]
        elif req.mode == "video":
            if req.height and req.ios_compatible:
                selector = (
                    f"bestvideo[height={req.height}][vcodec^=avc1]/"
                    f"bestvideo[height={req.height}][vcodec^=hvc1]/"
                    f"bestvideo[height={req.height}][vcodec^=hev1]/"
                    f"bestvideo[height={req.height}]/"
                    f"bestvideo[height<={req.height}]"
                )
            else:
                selector = f"bestvideo[height={req.height}]/bestvideo[height<={req.height}]" if req.height else "bestvideo"
            args += ["-f", selector, "--merge-output-format", "mkv", url]
        else:
            if req.height and req.ios_compatible:
                selector = (
                    f"bestvideo[height={req.height}][vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
                    f"bestvideo[height={req.height}][vcodec^=avc1]+bestaudio/"
                    f"bestvideo[height={req.height}][vcodec^=hvc1]+bestaudio/"
                    f"bestvideo[height={req.height}][vcodec^=hev1]+bestaudio/"
                    f"bestvideo[height={req.height}]+bestaudio/"
                    f"bestvideo[height<={req.height}]+bestaudio/"
                    f"best[height<={req.height}]"
                )
            else:
                selector = (
                    f"bestvideo[height={req.height}]+bestaudio/bestvideo[height<={req.height}]+bestaudio/best[height<={req.height}]"
                    if req.height else "bestvideo+bestaudio/best"
                )
            args += ["-f", selector, "--merge-output-format", "mkv", url]

        run_ytdlp_with_progress(job_id, args)

        source = find_final_source(workdir)
        source_probe = ffprobe(source)
        source_duration = float(source_probe.get("format", {}).get("duration") or title_info.get("duration") or 0)
        set_job(job_id, status="converting", progress="Preparing final file — 0.0%", stage_percent=0, percent=70, detail="Starting FFmpeg")

        prefix = "[MP4]" if req.container == "mp4" else "[MOV]"
        final_name = f"{prefix} {title}.{req.container}"
        final_path = job_dir / final_name

        if req.mode == "audio":
            ff = [
                "ffmpeg", "-y", "-i", str(source),
                "-map", "0:a:0",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                "-vn", "-movflags", "+faststart",
                str(final_path),
            ]
            run_ffmpeg_with_progress(job_id, ff, source_duration, "Preparing final file")
        else:
            if req.ios_compatible:
                source_video = next((x for x in source_probe.get("streams", []) if x.get("codec_type") == "video"), None)
                source_codec = (source_video or {}).get("codec_name", "").lower()
                can_copy_video = source_codec in {"h264", "hevc"}

                ff = ["ffmpeg", "-y", "-i", str(source), "-map", "0:v:0"]

                if can_copy_video:
                    # Fast path: keep an already Apple-friendly video stream and only fix the container/audio.
                    vcodec = ["-c:v", "copy"]
                    if source_codec == "hevc":
                        vcodec += ["-tag:v", "hvc1"]
                    set_job(
                        job_id,
                        progress="Preparing iOS file — 0.0%",
                        detail=f"Smart iOS: copying {source_codec.upper()} video (no video re-encode)",
                    )
                    label = "Preparing iOS file"
                else:
                    # Slow fallback: YouTube often exposes 1440p/4K as VP9/AV1 only.
                    # Convert only when necessary, using all available CPU and a speed-first x265 preset.
                    if req.height and req.height >= 1440:
                        vcodec = [
                            "-c:v", "libx265",
                            "-preset", "ultrafast",
                            "-crf", "23",
                            "-pix_fmt", "yuv420p",
                            "-tag:v", "hvc1",
                            "-threads", "0",
                        ]
                    else:
                        vcodec = [
                            "-c:v", "libx264",
                            "-preset", "veryfast",
                            "-crf", "20",
                            "-pix_fmt", "yuv420p",
                            "-profile:v", "high",
                            "-threads", "0",
                        ]
                    set_job(
                        job_id,
                        progress="Encoding iOS video — 0.0%",
                        detail=f"Smart iOS: {source_codec.upper() or 'source'} requires video conversion",
                    )
                    label = "Encoding iOS video"

                if req.mode == "av":
                    ff += ["-map", "0:a:0?", *vcodec, "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
                else:
                    ff += [*vcodec, "-an"]
                ff += ["-movflags", "+faststart", str(final_path)]
                run_ffmpeg_with_progress(job_id, ff, source_duration, label)
            else:
                ff = ["ffmpeg", "-y", "-i", str(source), "-map", "0", "-c", "copy", "-movflags", "+faststart", str(final_path)]
                run_ffmpeg_with_progress(job_id, ff, source_duration, "Remuxing final file")

        if not final_path.exists() or final_path.stat().st_size < 1024:
            raise RuntimeError("Final output is missing or invalid")

        probe = ffprobe(final_path)
        video = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), None)
        if req.mode != "audio" and req.height and video and int(video.get("height") or 0) < req.height:
            raise RuntimeError(f"Requested {req.height}p but output is {video.get('height')}p")

        set_job(
            job_id,
            status="done",
            progress="Done",
            stage_percent=100,
            percent=100,
            detail="",
            filename=final_name,
            size=final_path.stat().st_size,
            width=video.get("width") if video else None,
            height=video.get("height") if video else None,
            codec=video.get("codec_name") if video else None,
        )
        shutil.rmtree(workdir, ignore_errors=True)
    except Exception as exc:
        set_job(job_id, status="error", progress="Failed", error=str(exc)[-7000:])


@app.post("/api/download")
def start_download(req: DownloadRequest):
    cleanup_old_jobs()
    job_id = uuid.uuid4().hex
    job_dir = ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    with LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "created": time.time(),
            "status": "queued",
            "progress": "Queued",
        }
    thread = threading.Thread(target=download_job, args=(job_id, req), daemon=True)
    thread.start()
    return {"job_id": job_id}


@app.get("/api/status/{job_id}")
def status(job_id: str):
    cleanup_old_jobs()
    with LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return dict(job)


@app.get("/api/file/{job_id}")
def file(job_id: str):
    with LOCK:
        job = JOBS.get(job_id)
        if not job or job.get("status") != "done":
            raise HTTPException(status_code=404, detail="File is not ready")
        filename = job["filename"]
    path = ROOT / job_id / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File expired")
    media_type = "video/quicktime" if filename.lower().endswith(".mov") else "video/mp4"
    return FileResponse(path, filename=filename, media_type=media_type)
