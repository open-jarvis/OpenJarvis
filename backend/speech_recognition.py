import subprocess
import sys
import winsound
import whisper


def generate_test_audio(text, output_path="test.wav"):
    # Run pyttsx3 in a subprocess to avoid COM/torch conflict
    script = (
        f"import pyttsx3; e = pyttsx3.init(); "
        f"e.save_to_file({repr(text)}, {repr(output_path)}); e.runAndWait()"
    )
    subprocess.run([sys.executable, "-c", script], check=True)
    print(f"Test audio saved to: {output_path}")
    return output_path


def recognize_speech(wav_file):
    model = whisper.load_model("base")
    result = model.transcribe(wav_file)
    return result["text"]


def play_audio(audio_path):
    winsound.PlaySound(audio_path, winsound.SND_FILENAME)


if __name__ == "__main__":
    test_text = "Hello, this is a test of the speech recognition system."
    wav_file = generate_test_audio(test_text)

    transcription = recognize_speech(wav_file)
    print("Recognized:", transcription)

    play_audio(wav_file)
