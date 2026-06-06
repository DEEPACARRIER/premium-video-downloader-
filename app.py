from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp
import os
import json
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.service_account import Credentials

app = Flask(__name__)
TEMP_DIR = 'temp_downloads'
download_progress = {}

if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)

# 🚀 Force Clear Cache Settings
@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

def progress_hook(d):
    if d['status'] == 'downloading':
        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
        downloaded = d.get('downloaded_bytes', 0)
        if total > 0:
            download_progress['current'] = int((downloaded / total) * 100)
    elif d['status'] == 'finished':
        download_progress['current'] = 100

def upload_to_google_drive(file_path, file_name):
    try:
        SCOPES = ['https://www.googleapis.com/auth/drive.file']
        env_creds = os.environ.get('GOOGLE_CREDENTIALS_JSON')
        if not env_creds:
            return {"success": False, "message": "Server Config Error: GOOGLE_CREDENTIALS_JSON not found!"}
            
        creds_dict = json.loads(env_creds)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        service = build('drive', 'v3', credentials=creds)
        
        file_metadata = {'name': file_name}
        mimetype = 'audio/mp3' if file_path.endswith('.mp3') else 'video/mp4'
        media = MediaFileUpload(file_path, mimetype=mimetype, resumable=True)
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        
        return {"success": True, "file_id": file.get('id')}
    except Exception as e:
        return {"success": False, "message": str(e)}

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
    if not url: return jsonify({'success': False, 'message': 'Link missing!'})
    
    try:
        ydl_opts = {'extract_flat': 'in_playlist', 'skip_download': True, 'ignoreerrors': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info: return jsonify({'success': False, 'message': 'Could not extract info'})
            
            if 'entries' in info and info.get('_type') == 'playlist':
                playlist_videos = [{'title': e.get('title'), 'url': e.get('webpage_url')} for e in info['entries'] if e]
                return jsonify({'success': True, 'is_playlist': True, 'playlist_title': info.get('title'), 'videos': playlist_videos})
            
            available_formats = [{'id': 'bestaudio', 'resolution': 'High Quality Audio', 'size': 'Auto'}]
            for f in info.get('formats', []):
                if f.get('height') in [360, 480, 720, 1080]:
                    available_formats.append({'id': f.get('format_id'), 'resolution': f"{f.get('height')}p", 'size': 'Auto'})
            
            return jsonify({'success': True, 'is_playlist': False, 'title': info.get('title'), 'thumbnail': info.get('thumbnail'), 'formats': available_formats})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# 🔥 CORE DOWNLOAD ENGINE (FIXED FOR CORRUPTION)
def get_ydl_opts(format_id, start_time, end_time):
    opts = {
        'progress_hooks': [progress_hook],
        'outtmpl': f'{TEMP_DIR}/%(title)s.%(ext)s',
        'ignoreerrors': True,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'merge_output_format': 'mp4',
        'postprocessors': [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}]
    }
    
    if format_id == 'bestaudio':
        opts.update({'format': 'bestaudio/best', 'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}]})
    
    if (start_time and start_time != '00:00') or end_time:
        opts['download_ranges'] = lambda info, ctx: [{'start_time': yt_dlp.utils.timestr_to_secs(start_time or '00:00'), 'end_time': yt_dlp.utils.timestr_to_secs(end_time) if end_time else float('inf')}]
        opts['force_keyframes_at_cuts'] = True
    return opts

@app.route('/download', methods=['POST'])
def download():
    data = request.json
    ydl_opts = get_ydl_opts(data['format_id'], data.get('start_time'), data.get('end_time'))
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(data['url'], download=True)
        file_path = ydl.prepare_filename(info if 'entries' not in info else info['entries'][0])
        base, _ = os.path.splitext(file_path)
        final_path = base + ('.mp3' if data['format_id'] == 'bestaudio' else '.mp4')
        
    response = send_file(final_path, as_attachment=True)
    @response.call_on_close
    def cleanup(): 
        if os.path.exists(final_path): os.remove(final_path)
    return response

@app.route('/upload_drive', methods=['POST'])
def handle_drive_upload():
    data = request.json
    ydl_opts = get_ydl_opts(data['format_id'], data.get('start_time'), data.get('end_time'))
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(data['url'], download=True)
        file_path = ydl.prepare_filename(info if 'entries' not in info else info['entries'][0])
        base, _ = os.path.splitext(file_path)
        final_path = base + ('.mp3' if data['format_id'] == 'bestaudio' else '.mp4')
    
    res = upload_to_google_drive(final_path, os.path.basename(final_path))
    if os.path.exists(final_path): os.remove(final_path)
    return jsonify(res)

if __name__ == '__main__':
    app.run(debug=True)
