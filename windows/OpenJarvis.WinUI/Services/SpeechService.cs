using Windows.Foundation.Metadata;
using Windows.Media.Playback;
using Windows.Media.SpeechRecognition;
using Windows.Media.SpeechSynthesis;
using Windows.Storage.Streams;

namespace OpenJarvis.WinUI.Services;

/// <summary>Native Windows speech (WinRT), not the backend's <c>/v1/speech</c>
/// routes — those depend on Python packages (faster-whisper/ctranslate2,
/// Kokoro TTS/espeak-ng) with unreliable Windows ARM64 wheels. This app is
/// unpackaged (no .appxmanifest), so there is no manifest capability to
/// pre-declare microphone access — the first recognize call triggers the
/// OS's own privacy-broker consent, and a denial surfaces as
/// <see cref="UnauthorizedAccessException"/>, mapped to an actionable
/// message below rather than left as a raw exception.</summary>
public sealed class SpeechService : IDisposable
{
    private SpeechRecognizer? _recognizer;
    private MediaPlayer? _player;

    public static bool IsRecognitionAvailable()
    {
        try
        {
            return ApiInformation.IsTypePresent("Windows.Media.SpeechRecognition.SpeechRecognizer") &&
                SpeechRecognizer.SystemSpeechLanguage is not null;
        }
        catch
        {
            return false;
        }
    }

    public static bool IsSynthesisAvailable()
    {
        try
        {
            return ApiInformation.IsTypePresent("Windows.Media.SpeechSynthesis.SpeechSynthesizer");
        }
        catch
        {
            return false;
        }
    }

    /// <summary>Records one utterance and returns the recognized text, or
    /// null if nothing was recognized. Throws with an actionable message on
    /// failure (no mic, no speech language installed, permission denied).</summary>
    public async Task<string?> RecognizeOnceAsync(CancellationToken cancellationToken)
    {
        try
        {
            _recognizer ??= new SpeechRecognizer();
            await _recognizer.CompileConstraintsAsync();
            using var registration = cancellationToken.Register(() => _ = TryStopRecognizerAsync());
            var result = await _recognizer.RecognizeAsync();
            return result.Status == SpeechRecognitionResultStatus.Success
                ? result.Text
                : null;
        }
        catch (UnauthorizedAccessException)
        {
            throw new InvalidOperationException(
                "Microphone access is blocked. Enable it in Windows Settings → Privacy & security → Microphone, " +
                "and allow desktop apps to use the microphone.");
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            throw new InvalidOperationException(
                "Speech recognition is unavailable. Install a speech language under " +
                "Windows Settings → Time & language → Speech.", ex);
        }
    }

    private async Task TryStopRecognizerAsync()
    {
        try
        {
            if (_recognizer is not null)
            {
                await _recognizer.StopRecognitionAsync();
            }
        }
        catch
        {
            // Best effort.
        }
    }

    public bool IsSpeaking { get; private set; }

    public async Task SpeakAsync(string text, CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return;
        }

        StopSpeaking();
        try
        {
            using var synthesizer = new SpeechSynthesizer();
            using var stream = await synthesizer.SynthesizeTextToStreamAsync(text);
            _player = new MediaPlayer();
            var source = Windows.Media.Core.MediaSource.CreateFromStream(stream, stream.ContentType);
            _player.Source = source;
            IsSpeaking = true;
            var tcs = new TaskCompletionSource();
            void OnEnded(MediaPlayer sender, object args) => tcs.TrySetResult();
            _player.MediaEnded += OnEnded;
            _player.MediaFailed += (_, _) => tcs.TrySetResult();
            _player.Play();
            using var registration = cancellationToken.Register(() => tcs.TrySetResult());
            await tcs.Task;
            _player.MediaEnded -= OnEnded;
        }
        finally
        {
            IsSpeaking = false;
        }
    }

    public void StopSpeaking()
    {
        try
        {
            _player?.Pause();
            _player?.Dispose();
        }
        catch
        {
            // Best effort.
        }
        finally
        {
            _player = null;
            IsSpeaking = false;
        }
    }

    public void Dispose()
    {
        StopSpeaking();
        _recognizer?.Dispose();
    }
}
