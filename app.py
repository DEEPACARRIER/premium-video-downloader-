from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp
import os
import re

app = Flask(__name__)
TEMP_DIR = 'temp_downloads'
download_progress = {}

if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR, exist_ok=True)




@app.route('/')
def home():
    return render_template('index.html')

@app.route('/header')
def serve_header():
    return render_template('header.html')




# 🔥 Headers - Browser jaisa dikhne ke liye
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

# 🍪 Cookies file ka path (Render environment variable se)
COOKIES_FILE = os.environ.get('COOKIES_FILE_PATH', '')
if COOKIES_FILE and not os.path.exists(COOKIES_FILE):
    COOKIES_FILE = ''  # Agar file nahi hai to ignore kar do

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

def get_base_ydl_opts():
    """Common ydl options dono jagah use karne ke liye"""
    opts = {
        'headers': DEFAULT_HEADERS,
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
    }
    # Agar cookies file hai to add karo
    if COOKIES_FILE and os.path.exists(COOKIES_FILE):
        opts['cookiefile'] = COOKIES_FILE
    return opts

def progress_hook(d):
    if d['status'] == 'downloading':
        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 1
        downloaded = d.get('downloaded_bytes', 0)
        download_progress['current'] = int((downloaded / total) * 100)
    elif d['status'] == 'finished':
        download_progress['current'] = 100

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/get_progress', methods=['GET'])
def get_progress():
    return jsonify({'progress': download_progress.get('current', 0)})

@app.route('/get_info', methods=['POST'])
def get_info():
    data = request.json
    url = data.get('url')
    
    if not url:
        return jsonify({'success': False, 'message': 'URL empty!'})
    
    try:
        download_progress['current'] = 0
        
        # 🔥 YAHAN PEHLI JAGHA - cookies add ho gayi
        ydl_opts = get_base_ydl_opts()
        ydl_opts.update({
            'extract_flat': 'in_playlist',
            'skip_download': True,
        })
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if not info:
                return jsonify({'success': False, 'message': 'Cannot extract video info!'})
            
            # Playlist Check
            if 'entries' in info and info.get('_type') == 'playlist':
                playlist_videos = []
                for entry in info['entries']:
                    if entry:
                        v_url = entry.get('url') or entry.get('webpage_url')
                        if not v_url and entry.get('id'):
                            if 'youtube' in url:
                                v_url = f"https://www.youtube.com/watch?v={entry.get('id')}"
                            else:
                                v_url = entry.get('webpage_url')
                        
                        if v_url:
                            playlist_videos.append({
                                'title': entry.get('title', 'Untitled')[:70],
                                'url': v_url
                            })
                return jsonify({
                    'success': True,
                    'is_playlist': True,
                    'playlist_title': info.get('title', 'Playlist')[:70],
                    'videos': playlist_videos
                })
            
            # Single Video
            formats = info.get('formats', [])
            available_formats = []
            seen_resolutions = set()
            
            available_formats.append({
                'id': 'bestaudio',
                'resolution': 'Audio Only (MP3)',
                'size': '~ Auto'
            })
            
            for f in formats:
                res = f.get('height')
                if res and res >= 144:
                    res_name = f"{res}p"
                    if res_name not in seen_resolutions:
                        filesize = f.get('filesize') or f.get('filesize_approx') or 0
                        size_str = f"{round(filesize / (1024 * 1024), 2)} MB" if filesize > 0 else "Auto"
                        available_formats.append({
                            'id': f.get('format_id'),
                            'resolution': res_name,
                            'size': size_str
                        })
                        seen_resolutions.add(res_name)
            
            def get_res_num(x):
                try:
                    return int(x['resolution'].replace('p', '').split()[0])
                except:
                    return 999
            available_formats.sort(key=get_res_num)
            
            title = info.get('title', 'Video')[:80]
            duration_secs = info.get('duration')
            duration_str = f"{int(duration_secs)//60}:{int(duration_secs)%60:02d}" if duration_secs else "Live/Short"
            
            thumbnail = info.get('thumbnail') or info.get('thumbnails', [{}])[0].get('url') if info.get('thumbnails') else ''
            
            return jsonify({
                'success': True,
                'is_playlist': False,
                'title': title,
                'thumbnail': thumbnail,
                'duration': duration_str,
                'formats': available_formats
            })
            
    except Exception as e:
        print(f"Error in get_info: {str(e)}")
        return jsonify({'success': False, 'message': f'Error: {str(e)}'})

@app.route('/download', methods=['POST'])
def download():
    data = request.json
    url = data.get('url')
    format_id = data.get('format_id')
    
    if not url:
        return jsonify({'success': False, 'message': 'No URL provided'})
    
    download_progress['current'] = 0
    
    try:
        # 🔥 YAHAN DOOSRI JAGHA - cookies add ho gayi
        ydl_opts = get_base_ydl_opts()
        ydl_opts.update({
            'progress_hooks': [progress_hook],
            'outtmpl': f'{TEMP_DIR}/%(title)s.%(ext)s',
        })
        
        if format_id == 'bestaudio':
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })
        else:
            ydl_opts['format'] = f"{format_id}+bestaudio/best"
            ydl_opts['merge_output_format'] = 'mp4'

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            if 'entries' in info:
                info = info['entries'][0]
            
            file_path = ydl.prepare_filename(info)
            base, _ = os.path.splitext(file_path)
            file_path = base + ('.mp3' if format_id == 'bestaudio' else '.mp4')

        if os.path.exists(file_path):
            download_progress['current'] = 100
            response = send_file(file_path, as_attachment=True)
            
            @response.call_on_close
            def delete_temp_file():
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except:
                        pass
            
            return response
        
        return jsonify({'success': False, 'message': 'File not found'})
        
    except Exception as e:
        print(f"Download error: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
