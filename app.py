from flask import Flask, request, send_file, jsonify, send_from_directory
from flask_cors import CORS
import edge_tts
import os
import tempfile
import uuid
import asyncio
import traceback
import csv
import io
import requests

app = Flask(__name__)
CORS(app)

# =========================
# ASYNC HELPER
# =========================
def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

# =========================
# RATE FORMATTER
# =========================
def format_rate(rate):
    if not rate:
        return "+0%"
    rate = str(rate).replace("%", "").strip()
    if rate == "0":
        return "+0%"
    if rate.startswith("-"):
        return f"{rate}%"
    if rate.startswith("+"):
        return f"{rate}%"
    return f"+{rate}%"

# =========================
# SHEET DATA PROXY (CSV method)
# =========================
SHEET_ID = os.environ.get("SHEET_ID")
if not SHEET_ID:
    print("⚠️  WARNING: SHEET_ID environment variable not set. The default sheet won't load.")
    print("   Set it in Render dashboard: Key=SHEET_ID, Value=your_sheet_id")

def fetch_sheet_as_csv(sheet_id):
    """Fetch sheet data as CSV using Google Sheets export URL"""
    csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    resp = requests.get(csv_url)
    resp.raise_for_status()
    # Parse CSV
    content = resp.content.decode('utf-8')
    reader = csv.DictReader(io.StringIO(content))
    rows = []
    for row in reader:
        # Skip rows where both Khmer and Chinese are empty
        khmer = row.get('Khmer', '').strip() or row.get('km', '').strip() or row.get('ភាសា', '').strip()
        chinese = row.get('Chinese', '').strip() or row.get('zh', '').strip() or row.get('中文', '').strip()
        if khmer or chinese:
            rows.append({
                'khmer': khmer,
                'chinese': chinese,
                'sheetRow': len(rows) + 2  # +2 because row 1 is header, but we start at 2
            })
    return rows

@app.route('/api/sheet-data')
def sheet_data():
    try:
        custom_id = request.args.get('id')
        active_id = custom_id or SHEET_ID
        if not active_id:
            return jsonify({"error": "No sheet ID provided"}), 400

        rows = fetch_sheet_as_csv(active_id)
        return jsonify(rows)
    except Exception as e:
        print("Error fetching sheet:", traceback.format_exc())
        return jsonify({"error": str(e)}), 500

# =========================
# SERVE STATIC FILES (fonts, images)
# =========================
@app.route('/static/<path:path>')
def serve_static(path):
    # Try both folders
    if os.path.exists(os.path.join('static', path)):
        return send_from_directory('static', path)
    elif os.path.exists(os.path.join('public', 'static', path)):
        return send_from_directory('public/static', path)
    else:
        return "Not found", 404

# =========================
# SERVE INDEX.HTML
# =========================
@app.route('/')
def home():
    if os.path.exists('index.html'):
        with open('index.html', encoding='utf-8') as f:
            return f.read()
    elif os.path.exists('public/index.html'):
        with open('public/index.html', encoding='utf-8') as f:
            return f.read()
    else:
        return "index.html not found. Please ensure it's in the root or public/ folder.", 404

# =========================
# TTS GENERATE
# =========================
async def generate_tts(text, voice, rate, file_path):
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=format_rate(rate)
    )
    await communicate.save(file_path)

@app.route("/speak", methods=["GET", "POST"])
def speak():
    try:
        if request.method == "POST":
            text = request.form.get("text", "").strip()
            voice = request.form.get("voice", "zh-CN-XiaoxiaoNeural")
            rate = request.form.get("rate", "0")
        else:
            text = request.args.get("text", "").strip()
            voice = request.args.get("voice", "zh-CN-XiaoxiaoNeural")
            rate = request.args.get("rate", "0")

        if not text:
            return jsonify({"error": "No text provided"}), 400

        temp_dir = tempfile.gettempdir()
        filename = f"{uuid.uuid4().hex}.mp3"
        file_path = os.path.join(temp_dir, filename)

        print(f"🔵 Voice={voice}")
        print(f"🔵 Rate={rate}")
        print(f"🔵 Text={text[:50]}")

        run_async(generate_tts(text, voice, rate, file_path))

        if not os.path.exists(file_path) or os.path.getsize(file_path) < 1000:
            return jsonify({"error": "Audio file not created or too small"}), 500

        response = send_file(file_path, mimetype="audio/mpeg", as_attachment=False)

        @response.call_on_close
        def cleanup():
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                print("Cleanup error:", e)

        return response

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# =========================
# VOICE LIST
# =========================
@app.route("/voices")
def voices():
    try:
        voices = run_async(edge_tts.list_voices())
        return jsonify({
            "count": len(voices),
            "voices": [v["ShortName"] for v in voices]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# =========================
# HEALTH CHECK
# =========================
@app.route("/test")
def test():
    return jsonify({"status": "healthy"})

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Running on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
