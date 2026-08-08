from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
import edge_tts
import os
import tempfile
import uuid
import asyncio
import traceback
import requests

app = Flask(__name__)
CORS(app)

# =========================
# ASYNC HELPER
# =========================
def run_async(coro):
    """Safe asyncio runner for Flask"""
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
# TTS GENERATOR
# =========================
async def generate_tts(text, voice, rate, file_path):
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=format_rate(rate)
    )
    await communicate.save(file_path)

# =========================
# HOME
# =========================
@app.route("/")
def home():
    try:
        with open("index.html", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"index.html error: {e}", 500

# =========================
# GET VOCABULARY – with Google API fallback
# =========================
@app.route("/get_vocab")
def get_vocab():
    sheet_id = os.environ.get("GOOGLE_SHEETID")
    api_key = os.environ.get("GOOGLE_API_KEY")   # <-- new optional env var

    if not sheet_id:
        return jsonify({"error": "GOOGLE_SHEETID not set"}), 500

    # ---- If API key exists, use official Google Sheets API (no truncation) ----
    if api_key:
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/Sheet1?key={api_key}"
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            values = data.get('values', [])
            if not values:
                return jsonify({"error": "No data found in sheet"}), 404

            # Convert to list of dicts with column names as keys (compatible with frontend)
            headers = values[0]
            result = []
            for row in values[1:]:
                # Pad shorter rows to match header length
                while len(row) < len(headers):
                    row.append('')
                row_dict = {headers[i]: row[i] for i in range(len(headers))}
                result.append(row_dict)
            return jsonify(result)

        except requests.exceptions.RequestException as e:
            return jsonify({"error": f"Google API error: {str(e)}"}), 500
        except Exception as e:
            return jsonify({"error": f"Unexpected error: {str(e)}"}), 500

    # ---- Fallback to opensheet.elk.sh (may truncate at empty rows) ----
    url = f"https://opensheet.elk.sh/{sheet_id}/Sheet1"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return jsonify(data)
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Sheet fetch failed: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500

# =========================
# SPEAK
# =========================
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

        if not os.path.exists(file_path):
            return jsonify({"error": "Audio file not created"}), 500
        if os.path.getsize(file_path) < 1000:
            return jsonify({"error": "Audio file too small"}), 500

        response = send_file(
            file_path,
            mimetype="audio/mpeg",
            as_attachment=False
        )

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
# HEALTH CHECK
# =========================
@app.route("/test")
def test():
    return jsonify({"status": "healthy"})

# =========================
# DEBUG VOICES
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
# MAIN
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Running on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
