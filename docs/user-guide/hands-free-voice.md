# Hands-Free Voice

Talk to OpenJarvis in the desktop app by name, without clicking anything. Say **"Jarvis, what's on my calendar today?"** and it answers out loud. Follow-up questions within a few seconds don't need the name again.

Everything runs locally with the default stack: faster-whisper for speech-to-text, your local model for the answer, and Kokoro for the voice.

## Setup

### 1. Install the voice extra

Spoken replies use [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M), which is an optional extra. Run this once in your OpenJarvis checkout:

```bash
uv sync --extra desktop --extra inference-cloud --extra inference-google --group desktop-native --extra voice
```

The first reply after a restart takes a little longer while Kokoro loads (and, on the very first run, downloads its model and the spaCy English model). The desktop app's own dependency check at startup keeps these packages installed.

Without Kokoro, hands-free mode still works. Replies are then spoken with the operating system's built-in voice.

### 2. Turn it on

Open **Settings → Speech** and switch on **Hands-free voice**. You can also click the **Hands-free** pill above the chat box. The setting is remembered, so the app starts listening every time it opens.

## Using it

| You say | What happens |
|---|---|
| "Jarvis, what time is it in Tokyo?" | Answers out loud |
| "What's the weather like, Jarvis?" | The name also works at the end |
| "Jarvis." | A short chime: it is listening, ask your question |
| *(within ~8 s of a reply)* "And tomorrow?" | Follow-up, no name needed |
| "Thanks, that's all." / "Never mind." | Goes back to waiting for its name |
| "Jarvis, stop." *(while it talks)* | Stops the reply and listens |

The pill above the chat box shows what it is doing: **Say "Jarvis"**, **Listening…**, **Thinking…** or **Speaking…**. Press **Esc** or click the pill to stop a reply.

Voice turns ask the model for short, conversational answers without formatting, since they are read aloud. They appear in the chat history like typed messages.

It keeps working while the window is minimized or hidden to the tray. Closing the window quits the app.

## Changing the wake word

**Settings → Speech → Wake word** accepts any single word, for example `friday`. Recognition allows one-letter transcription slips for names of five letters or more ("Jervis" still wakes "Jarvis").

## Voice language

**Settings → Speech → Voice language** tells the speech recognizer which language you speak. The default, **Match system**, uses your system language. Whisper's automatic language detection is unreliable on a one-second clip like a bare "Jarvis" (it sometimes transcribes it in the wrong language), so pick **Auto-detect** only if you switch languages while talking.

## How it works

The app keeps the microphone open and cuts the audio into utterances with an energy-based voice activity detector that adapts to background noise. Each utterance is transcribed by the configured speech-to-text backend (`/v1/speech/transcribe`), with the wake word sent as a vocabulary hint (`hotwords`) so the name is not misheard. Only utterances addressed to the assistant by name are acted on; everything else is discarded. Audio never leaves your machine unless you configured a cloud speech backend.

While it is speaking, it only reacts to speech that is clearly louder than its own voice and starts with the wake word, so it does not answer itself.

## Troubleshooting

- **"No audio reached the app from your microphone"**: the microphone delivered only silence. Check that it is not muted, unplug and reconnect it, or pick another input in Windows sound settings.
- **It does not react to its name**: hover over the pill to see what it last heard. If the name comes out wrong, check the voice language and speak a little closer to the microphone.
- **The pill is greyed out**: no speech-to-text backend is available. Run `jarvis doctor` and check the speech backend line.
- **Replies are spoken in a robotic voice**: Kokoro is not installed or failed to load. Install the voice extra (step 1) and restart the app.
