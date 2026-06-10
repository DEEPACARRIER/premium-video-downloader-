from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp
import os

app = Flask(__name__)
TEMP_DIR = 'temp_downloads'
download_progress = {}

if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR, exist_ok=True)

# Headers taake server block na kare
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}

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

@app.route('/get_progress')
def get_progress():
    return jsonify({'progress': download_progress.get('current', 0)})

@app.route('/get_info', methods=['POST'])
def get_info():
    url = request.json.get('url')
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'headers': DEFAULT_HEADERS}) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Format list filter karein
            formats = []
            for f in info.get('formats', []):
                if f.get('height') and f['height'] >= 360:
                    formats.append({
                        'id': f['format_id'],
                        'resolution': f"{f['height']}p",
                        'size': f"{round((f.get('filesize') or 0)/1048576, 1)} MB" if f.get('filesize') else "Auto"
                    })
            
            return jsonify({
                'success': True,
                'title': info.get('title'),
                'thumbnail': info.get('thumbnail'),
                'formats': formats[:10] # Top 10 qualities
            })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/download', methods=['POST'])
def download():
    data = request.json
    url = data.get('url')
    format_id = data.get('format_id')
    
    # Unique filename ke liye
    file_tmpl = os.path.join(TEMP_DIR, '%(title)s.%(ext)s')
    
    ydl_opts = {
        'headers': DEFAULT_HEADERS,
        'format': f'{format_id}+bestaudio/best', # Video + Audio merge
        'outtmpl': file_tmpl,
        'progress_hooks': [progress_hook],
        'merge_output_format': 'mp4', # Force MP4 container
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4',
        }]
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            # Agar extension change hua ho (e.g. mkv to mp4)
            final_path = os.path.splitext(filename)[0] + ".mp4"
            
        return send_file(final_path, as_attachment=True)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

if __name__ == '__main__':
    app.run(debug=True)
