from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp
import os
import re

app = Flask(__name__)

TEMP_DIR = 'temp_downloads'
download_progress = {}

if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR, exist_ok=True)

# Browser headers
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

# Cookies file
COOKIES_FILE = os.environ.get('COOKIES_FILE_PATH', '')

if COOKIES_FILE and not os.path.exists(COOKIES_FILE):
    COOKIES_FILE = ''


@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response


def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name)


def get_base_ydl_opts():
    opts = {
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'headers': DEFAULT_HEADERS,
    }

    if COOKIES_FILE:
        opts['cookiefile'] = COOKIES_FILE

    return opts


def progress_hook(d):
    if d['status'] == 'downloading':
        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 1
        downloaded = d.get('downloaded_bytes', 0)

        percent = int((downloaded / total) * 100)
        download_progress['current'] = percent

    elif d['status'] == 'finished':
        download_progress['current'] = 100


@app.route('/')
def home():
    return render_template('index.html')


@app.route('/get_progress')
def get_progress():
    return jsonify({
        'progress': download_progress.get('current', 0)
    })


@app.route('/get_info', methods=['POST'])
def get_info():

    data = request.json
    url = data.get('url')

    if not url:
        return jsonify({
            'success': False,
            'message': 'URL missing'
        })

    try:

        ydl_opts = get_base_ydl_opts()

        ydl_opts.update({
            'skip_download': True,
            'extract_flat': False,
        })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:

            info = ydl.extract_info(url, download=False)

            if not info:
                return jsonify({
                    'success': False,
                    'message': 'Cannot fetch media info'
                })

            # PLAYLIST
            if 'entries' in info and info.get('_type') == 'playlist':

                videos = []

                for entry in info['entries']:

                    if not entry:
                        continue

                    video_url = entry.get('webpage_url')

                    if not video_url and entry.get('id'):
                        video_url = f"https://www.youtube.com/watch?v={entry.get('id')}"

                    videos.append({
                        'title': entry.get('title', 'Untitled')[:80],
                        'url': video_url
                    })

                return jsonify({
                    'success': True,
                    'is_playlist': True,
                    'playlist_title': info.get('title', 'Playlist'),
                    'videos': videos
                })

            # SINGLE VIDEO
            formats = info.get('formats', [])

            available_formats = []

            seen = set()

            # AUDIO OPTION
            available_formats.append({
                'id': 'bestaudio',
                'resolution': 'Audio MP3',
                'size': 'Auto'
            })

            for f in formats:

                height = f.get('height')

                # Only proper playable MP4 video formats
                if (
                    height and
                    height >= 144 and
                    f.get('ext') == 'mp4' and
                    f.get('vcodec') != 'none'
                ):

                    res = f"{height}p"

                    if res in seen:
                        continue

                    filesize = f.get('filesize') or f.get('filesize_approx') or 0

                    if filesize:
                        size = f"{round(filesize / (1024 * 1024), 2)} MB"
                    else:
                        size = "Auto"

                    available_formats.append({
                        'id': f.get('format_id'),
                        'resolution': res,
                        'size': size
                    })

                    seen.add(res)

            def sort_formats(x):
                try:
                    return int(x['resolution'].replace('p', '').split()[0])
                except:
                    return 9999

            available_formats.sort(key=sort_formats)

            duration = info.get('duration')

            if duration:
                mins = duration // 60
                secs = duration % 60
                duration_text = f"{mins}:{secs:02d}"
            else:
                duration_text = "Unknown"

            thumbnail = info.get('thumbnail')

            return jsonify({
                'success': True,
                'is_playlist': False,
                'title': sanitize_filename(info.get('title', 'Video'))[:80],
                'thumbnail': thumbnail,
                'duration': duration_text,
                'formats': available_formats
            })

    except Exception as e:
        print("INFO ERROR:", str(e))

        return jsonify({
            'success': False,
            'message': str(e)
        })


@app.route('/download', methods=['POST'])
def download():

    data = request.json

    url = data.get('url')
    format_id = data.get('format_id')

    if not url:
        return jsonify({
            'success': False,
            'message': 'No URL'
        })

    try:

        download_progress['current'] = 0

        ydl_opts = get_base_ydl_opts()

        ydl_opts.update({
            'progress_hooks': [progress_hook],
            'outtmpl': f'{TEMP_DIR}/%(title)s.%(ext)s',
            'noplaylist': True,
            'prefer_ffmpeg': True,
            'merge_output_format': 'mp4',
            'ffmpeg_location': 'ffmpeg',
        })

        # AUDIO DOWNLOAD
        if format_id == 'bestaudio':

            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]
            })

        # VIDEO DOWNLOAD
        else:

            ydl_opts.update({
                'format': f'{format_id}+bestaudio[ext=m4a]/best'
            })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:

            info = ydl.extract_info(url, download=True)

            if 'entries' in info:
                info = info['entries'][0]

            original_file = ydl.prepare_filename(info)

            base, ext = os.path.splitext(original_file)

            if format_id == 'bestaudio':
                final_file = base + '.mp3'
            else:
                final_file = base + '.mp4'

        if not os.path.exists(final_file):

            # fallback search
            for file in os.listdir(TEMP_DIR):

                if file.endswith('.mp4') or file.endswith('.mp3'):
                    final_file = os.path.join(TEMP_DIR, file)
                    break

        if os.path.exists(final_file):

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

        return jsonify({
            'success': False,
            'message': 'Downloaded file missing'
        })

    except Exception as e:

        print("DOWNLOAD ERROR:", str(e))

        return jsonify({
            'success': False,
            'message': str(e)
        })


if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=False
    )
