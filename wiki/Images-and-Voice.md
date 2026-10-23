# Images and Voice

AirLLM Studio sends images and audio **only to models that take them natively**. Nothing is converted for the model: there is no OCR for pictures and no speech-to-text step in front of a text model. If a model cannot take an input, its button simply is not shown.

## How Studio decides what a model can take

A model counts as able to **see** or **hear** only when all of these hold:

1. its checkpoint has the encoder (`vision_config` or `audio_config` in `config.json`),
2. AirLLM keeps that encoder **resident** in memory while it streams the language layers (otherwise it would stay unusable on the "meta" device), and
3. the processor files that turn pixels or sound into model inputs (`preprocessor_config.json` or `processor_config.json`) are in the download.

The result, `completion` (text), `vision` and/or `audio`, is stored with the model, shown as **Images** / **Voice** tags on the Models page, and returned as `capabilities` by `/api/show` and `/api/studio/models`.

## Images

Which models: vision-language models whose AirLLM class keeps the vision tower resident. Today that includes **Qwen3.8-27B** (in the suggested list), Qwen3.8-Flash-Next and Kimi K3. Models of other families can appear as text-only until AirLLM supports their vision tower.

In the app, for a vision model:

* press the **attach** button in the message box, or **paste** an image, or **drop** one onto the window;
* image thumbnails appear above the box; remove one with its **x**; click a sent image to enlarge it;
* ask your question and send. The model answers using the picture.

| Limit | Value |
|---|---|
| Image size | 20 MB each |
| Images per message | 8 |
| Formats | Anything Pillow can read (PNG, JPEG, WebP, GIF, ...); converted to RGB |

If you send an image to a model that cannot read images, Studio says so ("this model does not take images, pick a model that does") instead of quietly ignoring it. When you switch a chat to a text-only model, older images are replaced by `[image omitted]` so the conversation can continue.

## Voice

The microphone button appears only for models that understand audio, and **no model qualifies today**. The reason is in AirLLM, not Studio: AirLLM streams a model's language layers from disk, and none of its model classes keeps an *audio encoder* in memory, so speech-capable checkpoints (Qwen2-Audio, Voxtral, Qwen-Omni...) cannot run yet.

Everything on the Studio side is in place and tested for the day this changes: the button, recording up to 5 minutes in the browser, conversion to **16 kHz mono WAV**, and the server path that passes the audio to the model's processor (25 MB per clip, 8 per message).

Making it work is an upstream contribution: a model class per family that lists the audio tower and projector in `resident` layer names, next to the language model's layer names. See [Development](Development).

## Through the API

```sh
# Ollama style: base64 images on the message
curl http://127.0.0.1:11435/api/chat -d '{
  "model": "Qwen/Qwen3.8-27B", "stream": false,
  "messages": [{"role": "user", "content": "What is in this picture?", "images": ["<base64 jpeg or png>"]}]
}'
```

OpenAI style: `image_url` content parts with a **data URL** (`data:image/png;base64,...`); remote `http(s)` image URLs are **not** fetched (the server never makes requests on your behalf). Audio: `input_audio` parts with WAV data, or an `audio` list of base64 clips. More in [API Reference](API-Reference).
