from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp
import os
import json
import shutil
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.service_account import Credentials

app = Flask(__name__)
TEMP_DIR = 'temp_downloads'
download_progress = {}

# Folder setup
if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)

# --- UTILS ---
def clear_temp_folder():
    for filename in os.listdir(TEMP_DIR):
        file_path = os.path.join(TEMP_DIR, filename)
        try:
            if os.path.isfile(file_path): os.remove(file_path)
            elif os.path.isdir(file_path): shutil.rmtree(file_path)
        except Exception: pass

def progress_hook(d):
    if d['status'] == 'downloading':
        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 1
        downloaded = d.get('downloaded_bytes', 0)
        download_progress['current'] = int((downloaded / total) * 100)
    elif d['status'] == 'finished':
        download_progress['current'] = 100

# --- GOOGLE DRIVE ---
def upload_to_google_drive(file_path, file_name):
    try:
        env_creds = os.environ.get('GOOGLE_CREDENTIALS_JSON')
        if not env_creds:
            secret_path = '/etc/secrets/credentials.json'
            if os.path.exists(secret_path):
                with open(secret_path, 'r') as f: env_creds = f.read()
            else: return {"success": False, "message": "Credentials missing"}
        
        creds = Credentials.from_service_account_info(json.loads(env_creds), scopes=['https://www.googleapis.com/auth/drive.file'])
        service = build('drive', 'v3', credentials=creds)
        file_metadata = {'name': file_name, 'parents': ['root']}
        media = MediaFileUpload(file_path, resumable=True)
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return {"success": True, "file_id": file.get('id')}
    except Exception as e:
        return {"success": False, "message": str(e)}

# --- ROUTES ---
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/get_progress')
def get_progress():
    return jsonify({'progress': download_progress.get('current', 0)})

@app.route('/get_info', methods=['POST'])
def get_info():
    url = request.json.get('url')
    if not url: return jsonify({'success': False, 'message': 'No URL provided'})
    try:
        ydl_opts = {'extract_flat': 'in_playlist', 'skip_download': True, 'ignoreerrors': True, 'user_agent': 'Mozilla/5.0'}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info: raise Exception("Invalid Link")
            
            if info.get('_type') == 'playlist':
                return jsonify({'success': True, 'is_playlist': True, 'videos': [{'title': e.get('title'), 'url': e.get('url')} for e in info.get('entries', []) if e]})
            
            formats = [{'id': f.get('format_id'), 'resolution': f"{f.get('height')}p" if f.get('height') else 'Best'} 
                       for f in info.get('formats', []) if f.get('height') in [360, 480, 720, 1080]]
            return jsonify({'success': True, 'is_playlist': False, 'title': info.get('title'), 'formats': formats or [{'id': 'best', 'resolution': 'Best'}]})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/download', methods=['POST'])
def download():
    clear_temp_folder()
    data = request.json
    url, format_id = data.get('url'), data.get('format_id')
    try:
        opts = {
            'progress_hooks': [progress_hook],
            'outtmpl': f'{TEMP_DIR}/%(title)s.%(ext)s',
            'format': 'bestaudio/best' if format_id == 'bestaudio' else f"{format_id}+bestaudio/best",
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}] if format_id == 'bestaudio' else []
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info).rsplit('.', 1)[0] + ('.mp3' if format_id == 'bestaudio' else '.mp4')
        
        return send_file(filename, as_attachment=True)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/upload_drive', methods=['POST'])
def handle_drive_upload():
    clear_temp_folder()
    data = request.json
    url, format_id = data.get('url'), data.get('format_id')
    try:
        with yt_dlp.YoutubeDL({'outtmpl': f'{TEMP_DIR}/%(title)s.%(ext)s', 'format': 'best'}) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            res = upload_to_google_drive(file_path, os.path.basename(file_path))
            return jsonify(res)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

if __name__ == '__main__':
    app.run(debug=True)
