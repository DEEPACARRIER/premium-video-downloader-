```python
from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp
import os
import re
import glob

app = Flask(__name__)

# =========================
# CONFIG
# =========================
TEMP_DIR = "temp_downloads"
download_progress = {}

os.makedirs(TEMP_DIR, exist_ok=True)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

COOKIES_FILE = os.environ.get("COOKIES_FILE_PATH", "")

if COOKIES_FILE and not os.path.exists(COOKIES_FILE):
    COOKIES_FILE = ""


# =========================
# HELPERS
# =========================
def clean_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name)


def get_base_opts():
    opts = {
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "headers": DEFAULT_HEADERS,
        "nocheckcertificate": True,
    }

    if COOKIES_FILE:
        opts["cookiefile"] = COOKIES_FILE

    return opts


def progress_hook(d):
    try:
        if d["status"] == "downloading":

            total = (
                d.get("total_bytes")
                or d.get("total_bytes_estimate")
                or 1
            )

            downloaded = d.get("downloaded_bytes", 0)

            percent = int((downloaded / total) * 100)

            if percent > 100:
                percent = 100

            download_progress["current"] = percent

        elif d["status"] == "finished":
            download_progress["current"] = 100

    except:
        pass


@app.after_request
def add_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "-1"
    return response


# =========================
# ROUTES
# =========================
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/get_progress")
def get_progress():
    return jsonify({
        "progress": download_progress.get("current", 0)
    })


# =========================
# GET VIDEO INFO
# =========================
@app.route("/get_info", methods=["POST"])
def get_info():

    try:

        data = request.get_json()

        url = data.get("url", "").strip()

        if not url:
            return jsonify({
                "success": False,
                "message": "URL missing"
            })

        download_progress["current"] = 0

        ydl_opts = get_base_opts()

        ydl_opts.update({
            "skip_download": True,
            "extract_flat": False,
            "noplaylist": False,
        })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:

            info = ydl.extract_info(url, download=False)

            if not info:
                return jsonify({
                    "success": False,
                    "message": "Cannot fetch media information"
                })

            # =========================
            # PLAYLIST
            # =========================
            if info.get("_type") == "playlist" and "entries" in info:

                playlist_videos = []

                for entry in info["entries"]:

                    if not entry:
                        continue

                    v_url = (
                        entry.get("webpage_url")
                        or entry.get("url")
                    )

                    if not v_url and entry.get("id"):
                        v_url = f"https://www.youtube.com/watch?v={entry.get('id')}"

                    playlist_videos.append({
                        "title": entry.get("title", "Untitled")[:80],
                        "url": v_url
                    })

                return jsonify({
                    "success": True,
                    "is_playlist": True,
                    "playlist_title": info.get("title", "Playlist"),
                    "videos": playlist_videos
                })

            # =========================
            # SINGLE VIDEO
            # =========================
            formats = info.get("formats", [])

            available_formats = []

            seen = set()

            # AUDIO
            available_formats.append({
                "id": "bestaudio",
                "resolution": "Audio MP3",
                "size": "Auto"
            })

            for f in formats:

                try:

                    height = f.get("height")

                    if not height:
                        continue

                    if height < 144:
                        continue

                    if f.get("vcodec") == "none":
                        continue

                    format_id = f.get("format_id")

                    if not format_id:
                        continue

                    res = f"{int(height)}p"

                    if res in seen:
                        continue

                    filesize = (
                        f.get("filesize")
                        or f.get("filesize_approx")
                        or 0
                    )

                    if filesize:
                        size = f"{round(filesize / (1024 * 1024), 2)} MB"
                    else:
                        size = "Auto"

                    available_formats.append({
                        "id": format_id,
                        "resolution": res,
                        "size": size
                    })

                    seen.add(res)

                except:
                    pass

            # SORT
            def sort_formats(x):
                try:
                    return int(
                        x["resolution"]
                        .replace("p", "")
                        .split()[0]
                    )
                except:
                    return 9999

            available_formats.sort(key=sort_formats)

            # DURATION
            duration = info.get("duration")

            if duration:
                duration = int(float(duration))

                mins = duration // 60
                secs = duration % 60

                duration_text = f"{mins}:{secs:02d}"
            else:
                duration_text = "Unknown"

            # THUMBNAIL
            thumbnail = info.get("thumbnail")

            if not thumbnail:
                thumbs = info.get("thumbnails", [])

                if thumbs and len(thumbs) > 0:
                    thumbnail = thumbs[-1].get("url", "")

            return jsonify({
                "success": True,
                "is_playlist": False,
                "title": clean_filename(
                    info.get("title", "Video")
                )[:100],
                "thumbnail": thumbnail,
                "duration": duration_text,
                "formats": available_formats
            })

    except Exception as e:

        print("GET INFO ERROR:", str(e))

        return jsonify({
            "success": False,
            "message": str(e)
        })


# =========================
# DOWNLOAD
# =========================
@app.route("/download", methods=["POST"])
def download():

    try:

        data = request.get_json()

        url = data.get("url", "").strip()
        format_id = data.get("format_id", "").strip()

        if not url:
            return jsonify({
                "success": False,
                "message": "URL missing"
            })

        download_progress["current"] = 0

        # CLEAN OLD FILES
        for file in glob.glob(f"{TEMP_DIR}/*"):
            try:
                os.remove(file)
            except:
                pass

        ydl_opts = get_base_opts()

        ydl_opts.update({
            "progress_hooks": [progress_hook],
            "outtmpl": f"{TEMP_DIR}/%(title)s.%(ext)s",
            "noplaylist": True,
            "prefer_ffmpeg": True,
            "merge_output_format": "mp4",
            "ffmpeg_location": "ffmpeg",
            "overwrites": True,
        })

        # =========================
        # AUDIO
        # =========================
        if format_id == "bestaudio":

            ydl_opts.update({
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }]
            })

        # =========================
        # VIDEO
        # =========================
        else:

            # Most compatible universal format
            ydl_opts.update({
                "format": f"{format_id}+bestaudio/best"
            })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:

            info = ydl.extract_info(url, download=True)

            if not info:
                return jsonify({
                    "success": False,
                    "message": "Download failed"
                })

            if "entries" in info:
                info = info["entries"][0]

            original_file = ydl.prepare_filename(info)

            base, ext = os.path.splitext(original_file)

            if format_id == "bestaudio":
                final_file = base + ".mp3"
            else:
                final_file = base + ".mp4"

        # FALLBACK SEARCH
        if not os.path.exists(final_file):

            found = False

            for file in os.listdir(TEMP_DIR):

                if format_id == "bestaudio":
                    if file.endswith(".mp3"):
                        final_file = os.path.join(TEMP_DIR, file)
                        found = True
                        break
                else:
                    if (
                        file.endswith(".mp4")
                        or file.endswith(".mkv")
                        or file.endswith(".webm")
                    ):
                        final_file = os.path.join(TEMP_DIR, file)
                        found = True
                        break

            if not found:
                return jsonify({
                    "success": False,
                    "message": "Downloaded file not found"
                })

        download_progress["current"] = 100

        response = send_file(
            final_file,
            as_attachment=True
        )

        @response.call_on_close
        def cleanup():

            try:
                if os.path.exists(final_file):
                    os.remove(final_file)
            except:
                pass

        return response

    except Exception as e:

        print("DOWNLOAD ERROR:", str(e))

        return jsonify({
            "success": False,
            "message": str(e)
        })


# =========================
# MAIN
# =========================
if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )
```
