const express = require('express');
const { EdgeTTS } = require('edge-tts');

const app = express();
const tts = new EdgeTTS();

// ========== SHEET DATA PROXY ==========
const SHEET_ID = process.env.SHEET_ID;
if (!SHEET_ID) {
  console.error("ERROR: SHEET_ID environment variable not set on Render!");
  process.exit(1);
}

app.use(express.static('public'));
app.use('/static', express.static('static'));

app.get('/api/sheet-data', async (req, res) => {
  try {
    const customId = req.query.id;
    const activeId = customId || SHEET_ID;
    const url = `https://opensheet.elk.sh/${activeId}/Sheet1`;
    const response = await fetch(url);
    const data = await response.json();
    res.json(data);
  } catch (error) {
    console.error("Proxy error:", error);
    res.status(500).json({ error: "Failed to fetch sheet data" });
  }
});

// ========== TTS PROXY (USING EDGE TTS) ==========
app.use(express.urlencoded({ extended: true }));

app.post('/speak', async (req, res) => {
  try {
    const { text, voice, rate } = req.body;
    if (!text) {
      return res.status(400).send('Missing text');
    }

    // Build the SSML with optional rate
    let ssml = `<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">`;
    if (rate && rate !== '0%') {
      const rateValue = rate.replace('%', '');
      const rateNum = parseFloat(rateValue);
      if (!isNaN(rateNum)) {
        const speed = rateNum >= 0 ? `+${rateNum}%` : `${rateNum}%`;
        ssml += `<prosody rate="${speed}">${text}</prosody>`;
      } else {
        ssml += text;
      }
    } else {
      ssml += text;
    }
    ssml += `</speak>`;

    // Generate audio using Edge TTS
    const audioStream = await tts.toStream({
      text: ssml,
      voice: voice || 'zh-CN-YunxiNeural',
      rate: rate || '0%'
    });

    // Set headers for audio playback
    res.setHeader('Content-Type', 'audio/mpeg');
    audioStream.pipe(res);
  } catch (error) {
    console.error('TTS error:', error);
    res.status(500).send('TTS generation failed');
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Server running on port ${PORT}`));