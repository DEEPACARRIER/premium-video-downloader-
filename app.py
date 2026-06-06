Flask, render_template, request, jsonify, send_file

import yt_dlp

import os

import requests

import json



# Google Drive API Imports

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



# ☁️ GOOGLE DRIVE UPLOAD CORE FUNCTION (SAFE ENVIRONMENT VERSION)

# Updated Upload Function

def upload_to_google_drive(file_path, file_name):

    try:

        SCOPES = ['https://www.googleapis.com/auth/drive.file']

        

        # Pehle variable check karein, agar na mile toh file path check karein

        env_creds = os.environ.get('GOOGLE_CREDENTIALS_JSON')

        

        if not env_creds:

            # Agar variable khali hai, toh secret file se read karo

            secret_file_path = '/etc/secrets/credentials.json'

            if os.path.exists(secret_file_path):

                with open(secret_file_path, 'r') as f:

                    env_creds = f.read()

            else:

                return {"success": False, "message": "Critical Error: credentials file nahi mili!"}

            

        creds_dict = json.loads(env_creds)

        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)

        service = build('drive', 'v3', credentials=creds)

        # ... (baqi code waisa hi rahega)

        

        # Yahan 'parents' mein us folder ki ID dalen jahan file bhejni hai

        # Agar folder ID nahi hai, toh file "root" mein jayegi (service account ki drive mein)

        file_metadata = {

            'name': file_name,

            'parents': ['root'] # Yahan user ke folder ki ID bhi di ja sakti hai

        }

        

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

    if not url:

        return jsonify({'success': False, 'message': 'Link khali hai!'})

    

    try:

        download_progress['current'] = 0

        

        ydl_opts = {

            'extract_flat': 'in_playlist', 

            'skip_download': True,

            'ignoreerrors': True

        }

        

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:

            info = ydl.extract_info(url, download=False)

            

            if not info:

                return jsonify({'success': False, 'message': 'Video ki details nahi nikal sakeen. Link dobara check karein!'})

            

            # 📜 1. AUTO PLAYLIST DETECTOR

            if 'entries' in info and info.get('_type') == 'playlist':

                playlist_videos = []

                for entry in info['entries']:

                    if entry:

                        v_url = entry.get('url') or entry.get('webpage_url')

                        if not v_url and entry.get('id'):

                            v_url = f"https://www.youtube.com/watch?v={entry.get('id')}"

                        

                        if v_url:

                            playlist_videos.append({

                                'title': entry.get('title', 'Untitled Video'),

                                'url': v_url

                            })

                return jsonify({

                    'success': True,

                    'is_playlist': True,

                    'playlist_title': info.get('title', 'Playlist'),

                    'videos': playlist_videos

                })

                

            # 🎬 2. UNIVERSAL SINGLE VIDEO PARSER

            formats = info.get('formats', [])

            available_formats = []

            seen_resolutions = set()

            

            available_formats.append({

                'id': 'bestaudio',

                'type': '🎵 Audio (MP3)',

                'resolution': 'High Quality Audio',

                'size': 'Auto Size'

            })

            

            for f in formats:

                res = f.get('height')

                if res and res in [360, 480, 720, 1080]:

                    res_name = f"{res}p"

                    if res_name not in seen_resolutions:

                        filesize = f.get('filesize') or f.get('filesize_approx') or 0

                        try:

                            size_str = f"{round(float(filesize) / (1024 * 1024), 2)} MB" if filesize > 0 else "Auto Size"

                        except:

                            size_str = "Auto Size"

                            

                        available_formats.append({

                            'id': f.get('format_id'),

                            'type': 'MP4',

                            'resolution': res_name,

                            'size': size_str

                        })

                        seen_resolutions.add(res_name)



            if len(available_formats) <= 1:

                available_formats.append({

                    'id': 'best',

                    'type': 'MP4 (Universal)',

                    'resolution': 'Best Quality',

                    'size': 'Auto Size'

                })

            

            title = info.get('title') or info.get('description', 'Social Media Video')

            if len(title) > 60: title = title[:57] + "..."

                

            duration_secs = info.get('duration')

            duration_str = f"{int(duration_secs) // 60}:{int(duration_secs) % 60:02d}" if duration_secs else "Live/Short"

            

            return jsonify({

                'success': True,

                'is_playlist': False,

                'title': title,

                'thumbnail': info.get('thumbnail') or info.get('thumbnails', [{}])[0].get('url') or 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe',

                'duration': duration_str,

                'formats': available_formats

            })

            

    except Exception as e:

        return jsonify({'success': False, 'message': f'Server Processing Error: {str(e)}'})



# 📥 REGULAR LOCAL DOWNLOAD ROUTE

@app.route('/download', methods=['POST'])

def download():

    data = request.json

    url = data.get('url')

    format_id = data.get('format_id')

    

    download_progress['current'] = 0

    try:

        ydl_opts = {

            'progress_hooks': [progress_hook], 

            'outtmpl': f'{TEMP_DIR}/%(title)s.%(ext)s',

            'ignoreerrors': True

        }

        

        if format_id == 'bestaudio':

            ydl_opts.update({

                'format': 'bestaudio/best',

                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],

            })

        else:

            if format_id == 'best':

                ydl_opts['format'] = 'best'

            else:

                ydl_opts['format'] = f"{format_id}+bestaudio/best"

                ydl_opts['merge_output_format'] = 'mp4'



        with yt_dlp.YoutubeDL(ydl_opts) as ydl:

            info = ydl.extract_info(url, download=True)

            if 'entries' in info: info = info['entries'][0]

            file_path = ydl.prepare_filename(info)

            base, _ = os.path.splitext(file_path)

            file_path = base + ('.mp3' if format_id == 'bestaudio' else '.mp4')



        if os.path.exists(file_path):

            download_progress['current'] = 100

            response = send_file(file_path, as_attachment=True)

            @response.call_on_close

            def delete_temp_file():

                if os.path.exists(file_path): os.remove(file_path)

            return response

        return jsonify({'success': False, 'message': 'Download failed'})

    except Exception as e:

        return jsonify({'success': False, 'message': str(e)})



# ☁️ REAL GOOGLE DRIVE PIPELINE ROUTE

@app.route('/upload_drive', methods=['POST'])

def handle_drive_upload():

    data = request.json

    url = data.get('url')

    format_id = data.get('format_id')

    start_time = data.get('start_time', '00:00')

    end_time = data.get('end_time', '')

    

    download_progress['current'] = 0

    try:

        ydl_opts = {

            'progress_hooks': [progress_hook], 

            'outtmpl': f'{TEMP_DIR}/%(title)s.%(ext)s', 

            'ignoreerrors': True, 

            'ext': 'mp4'

        }

        

        if format_id == 'bestaudio':

            ydl_opts.update({

                'format': 'bestaudio/best', 

                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}]

            })

        else:

            if format_id == 'best' or 'instagram' in url.lower() or 'facebook' in url.lower():

                ydl_opts['format'] = 'best'

            else:

                ydl_opts['format'] = f"{format_id}+bestaudio/best"

                ydl_opts['merge_output_format'] = 'mp4'



        if (start_time and start_time != '00:00') or end_time:

            ydl_opts['download_ranges'] = lambda info, ctx: [{

                'start_time': yt_dlp.utils.timestr_to_secs(start_time or '00:00'), 

                'end_time': yt_dlp.utils.timestr_to_secs(end_time) if end_time else float('inf')

            }]

            ydl_opts['force_keyframes_at_cuts'] = True



        with yt_dlp.YoutubeDL(ydl_opts) as ydl:

            info = ydl.extract_info(url, download=True)

            if 'entries' in info: 

                info = info['entries'][0]

            file_path = ydl.prepare_filename(info)

            

            base, _ = os.path.splitext(file_path)

            ext = '.mp3' if format_id == 'bestaudio' else '.mp4'

            file_path = base + ext

            display_name = (info.get('title') or 'Cloud_File') + ext



        if os.path.exists(file_path):

            # Google Drive API calling

            drive_result = upload_to_google_drive(file_path, display_name)

            

            # File ko space khali karne ke liye fauran delete karna

            if os.path.exists(file_path): 

                os.remove(file_path)

                

            return jsonify(drive_result)

        else:

            return jsonify({'success': False, 'message': 'Download failed before cloud compilation.'})

    except Exception as e:

        return jsonify({'success': False, 'message': str(e)})



if __name__ == '__main__':

    app.run(debug=True) 

