from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp
import os
import requests

app = Flask(__name__)
TEMP_DIR = 'temp_downloads'

# Global variable live progress track karne ke liye
download_progress = {}

if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)

# 🚀 FORCE BROWSER TO CLEAR CACHE (Yeh aapka masla hal karega)
@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

# yt-dlp ka progress hook jo download percentage nikalta hai
def progress_hook(d):
    if d['status'] == 'downloading':
        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
        downloaded = d.get('downloaded_bytes', 0)
        if total > 0:
            percent = int((downloaded / total) * 100)
            download_progress['current'] = percent
    elif d['status'] == 'finished':
        download_progress['current'] = 100

@app.route('/')
def home():
    return render_template('index.html')

# Live progress check karne ka API endpoint
@app.route('/get_progress', methods=['GET'])
def get_progress():
    return jsonify({'progress': download_progress.get('current', 0)})

@app.route('/get_info', methods=['POST'])
def get_info():
    data = request.json
    url = data.get('url')
    if not url:
        return jsonify({'success': False, 'message': 'Link khali hai!'})
    
    try:
        download_progress['current'] = 0 # reset progress
        with yt_dlp.YoutubeDL() as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats', [])
            
            available_formats = []
            seen_resolutions = set()
            
            # Audio format
            audio_size = "N/A"
            for f in formats:
                if f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                    filesize = f.get('filesize') or f.get('filesize_approx')
                    if filesize:
                        audio_size = f"{round(filesize / (1024 * 1024), 2)} MB"
                        break
            
            available_formats.append({
                'id': 'bestaudio',
                'type': '🎵 Audio (MP3)',
                'resolution': '192kbps',
                'size': audio_size
            })
            
            # Video formats (360p, 480p, 720p, 1080p)
            for f in formats:
                res = f.get('height')
                if res in [360, 480, 720, 1080]:
                    res_name = f"{res}p"
                    if res_name not in seen_resolutions:
                        filesize = f.get('filesize') or f.get('filesize_approx')
                        size_str = f"{round(filesize / (1024 * 1024), 2)} MB" if filesize else "Calculated"
                        
                        available_formats.append({
                            'id': f.get('format_id'),
                            'type': 'MP4',
                            'resolution': res_name,
                            'size': size_str
                        })
                        seen_resolutions.add(res_name)
            
            if len(available_formats) == 1:
                available_formats.append({'id': 'best', 'type': 'MP4', 'resolution': 'Best Quality', 'size': 'Auto'})
                
            return jsonify({
                'success': True, 
                'title': info.get('title', 'Video'), 
                'thumbnail': info.get('thumbnail', ''),
                'duration': f"{info.get('duration', 0) // 60}:{info.get('duration', 0) % 60:02d}",
                'formats': available_formats
            })
            
    except Exception as e:
        return jsonify({'success': False, 'message': f'Video nahi mil saki: {str(e)}'})

@app.route('/download', methods=['POST'])
def download():
    data = request.json
    url = data.get('url')
    format_id = data.get('format_id')
    start_time = data.get('start_time', '00:00')
    end_time = data.get('end_time', '')
    
    download_progress['current'] = 0
    
    try:
        ydl_opts = {
            'progress_hooks': [progress_hook],
            'merge_output_format': 'mp4',
        }
        
        if format_id == 'bestaudio':
            ydl_opts.update({
                'format': 'bestaudio/best',
                'outtmpl': f'{TEMP_DIR}/%(title)s.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })
        else:
            if format_id != 'best':
                ydl_opts['format'] = f"{format_id}+bestaudio/best"
            else:
                ydl_opts['format'] = 'bestvideo+bestaudio/best'
                
            ydl_opts['outtmpl'] = f'{TEMP_DIR}/%(title)s.%(ext)s'

        if start_time != '00:00' or end_time != '':
            ydl_opts['download_ranges'] = lambda info, ctx: [{
                'start_time': yt_dlp.utils.timestr_to_secs(start_time or '00:00'), 
                'end_time': yt_dlp.utils.timestr_to_secs(end_time) if end_time else float('inf')
            }]
            ydl_opts['force_keyframes_at_cuts'] = True

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            
            if format_id == 'bestaudio':
                file_path = os.path.splitext(file_path)[0] + '.mp3'
            else:
                file_path = os.path.splitext(file_path)[0] + '.mp4'

        if os.path.exists(file_path):
            download_progress['current'] = 100
            response = send_file(file_path, as_attachment=True)
            
            @response.call_on_close
            def delete_temp_file():
                if os.path.exists(file_path):
                    os.remove(file_path)
            return response
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/download_thumb', methods=['POST'])
def download_thumb():
    data = request.json
    thumb_url = data.get('thumb_url')
    try:
        img_data = requests.get(thumb_url).content
        file_path = os.path.join(TEMP_DIR, 'thumbnail.jpg')
        with open(file_path, 'wb') as handler:
            handler.write(img_data)
        if os.path.exists(file_path):
            response = send_file(file_path, as_attachment=True, download_name='Thumbnail.jpg')
            @response.call_on_close
            def delete_temp_file():
                if os.path.exists(file_path):
                    os.remove(file_path)
            return response
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

if __name__ == '__main__':
    app.run(debug=True)