using System.Diagnostics;
using OpenJarvis.WinUI.Models;

namespace OpenJarvis.WinUI.Services;

public sealed class BackendSupervisor : IDisposable
{
    private readonly JarvisApiClient _api;
    private readonly FoundryClient _foundry;
    private readonly SettingsStore _settings;
    private readonly NativeJob _job = new();
    private Process? _jarvis;
    private Task? _drain;
    private CancellationTokenSource? _loop;
    private Task _loopTask = Task.CompletedTask;
    private int _backoffMs = 1000;
    private readonly object _logGate = new();
    private string _recentOutput = "";

    public BackendSupervisor(JarvisApiClient api, FoundryClient foundry, SettingsStore settings)
    {
        _api = api;
        _foundry = foundry;
        _settings = settings;
    }

    public BackendStatus Status { get; } = new();
    public event EventHandler? StatusChanged;

    public string LastError { get; private set; } = "";

    public void ReportUiError(string message)
    {
        LastError = message;
        Status.Failed = true;
        Status.Detail = message;
        StatusChanged?.Invoke(this, EventArgs.Empty);
    }

    public void Start()
    {
        _loop?.Cancel();
        _loop = new CancellationTokenSource();
        _backoffMs = 1000;
        var token = _loop.Token;
        var previous = _loopTask;
        _loopTask = Task.Run(async () =>
        {
            // A cancelled loop may still be unwinding a Foundry or jarvis child process.
            await previous.ContinueWith(_ => { }, TaskScheduler.Default);
            await SuperviseAsync(token);
        });
    }

    /// <summary>
    /// Cancels setup and stops jarvis serve. Foundry Local's own daemon is left alone
    /// because other apps on the machine may be using it.
    /// </summary>
    public async Task StopAsync()
    {
        _loop?.Cancel();
        await _loopTask.ContinueWith(_ => { }, TaskScheduler.Default);
        StopJarvis();
        SetStatus(SetupStep.Engine, "Stopped", "Setup stopped.", false);
    }

    public async Task RestartWithModelAsync(string model, CancellationToken cancellationToken)
    {
        _settings.Current.SelectedModel = model;
        _settings.Save();
        await LoadSelectedModelAsync(cancellationToken);
        StopJarvis();
        SetStatus(SetupStep.Server, "Restarting", $"Switching model to {model}…", false);
        await StartJarvisAsync(cancellationToken);
        await WaitUntilReadyAsync(cancellationToken);
    }

    public void Dispose()
    {
        _loop?.Cancel();
        StopJarvis();
        _job.Dispose();
    }

    private async Task SuperviseAsync(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            try
            {
                _api.SetBaseUrl(_settings.Current.ApiUrl);
                SetStatus(SetupStep.Engine, "Checking backend", "Looking for a local OpenJarvis server…", false);
                using var shortWait = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
                shortWait.CancelAfter(TimeSpan.FromSeconds(2));
                if (await _api.IsHealthyAsync(shortWait.Token))
                {
                    await LoadSelectedModelAsync(cancellationToken);
                    SetStatus(SetupStep.Done, "Ready", "Attached to an existing OpenJarvis server.", false);
                    _backoffMs = 1000;
                    await WaitUntilUnhealthyAsync(cancellationToken);
                    continue;
                }

                SetStatus(SetupStep.Engine, "Starting Foundry Local", "Ensuring Foundry Local is installed and running…", false);
                var progress = new Progress<string>(line =>
                    SetStatus(SetupStep.Engine, "Starting Foundry Local", line, false));
                var host = await _foundry.EnsureServiceAsync(cancellationToken, progress);
                TomlSettings.SetFoundryHost(host);
                await LoadSelectedModelAsync(cancellationToken);

                SetStatus(SetupStep.Server, "Starting OpenJarvis", "Launching jarvis serve…", false);
                await StartJarvisAsync(cancellationToken);

                var deadline = DateTime.UtcNow.AddMinutes(10);
                while (DateTime.UtcNow < deadline && !cancellationToken.IsCancellationRequested)
                {
                    if (await _api.IsEngineHealthyAsync(cancellationToken))
                    {
                        SetStatus(SetupStep.Done, "Ready", "OpenJarvis is ready.", false);
                        _backoffMs = 1000;
                        await WaitUntilUnhealthyAsync(cancellationToken);
                        break;
                    }

                    if (_jarvis is { HasExited: true })
                    {
                        throw new InvalidOperationException(await FormatExitAsync(_jarvis, cancellationToken));
                    }

                    SetStatus(SetupStep.Server, "Waiting", "Waiting for /health…", false);
                    await Task.Delay(1000, cancellationToken);
                }
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                return;
            }
            catch (Exception ex)
            {
                LastError = ex.Message;
                SetStatus(Status.Step, "Error", Actionable(ex.Message), true);
                try
                {
                    await Task.Delay(_backoffMs, cancellationToken);
                }
                catch (OperationCanceledException)
                {
                    return;
                }

                _backoffMs = Math.Min(_backoffMs * 2, 30_000);
            }
        }
    }

    private async Task LoadSelectedModelAsync(CancellationToken cancellationToken)
    {
        var model = _settings.Current.SelectedModel;
        if (string.IsNullOrWhiteSpace(model))
        {
            return;
        }

        SetStatus(SetupStep.Model, "Loading model", $"Loading {model} into Foundry Local…", false);
        var progress = new Progress<string>(line =>
            SetStatus(SetupStep.Model, "Loading model", line, false));
        var loaded = await _foundry.EnsureModelLoadedAsync(model, cancellationToken, progress);
        if (!string.IsNullOrWhiteSpace(loaded) &&
            !string.Equals(loaded, model, StringComparison.OrdinalIgnoreCase))
        {
            _settings.Current.SelectedModel = loaded;
            _settings.Save();
            SetStatus(
                SetupStep.Model,
                "Loading model",
                $"This device cannot load {model}. Using {loaded} instead.",
                false);
        }
    }

    private async Task StartJarvisAsync(CancellationToken cancellationToken)
    {
        StopJarvis();
        lock (_logGate)
        {
            _recentOutput = "";
        }

        var jarvis = AppPaths.JarvisExecutable();
        var devRoot = AppPaths.DevProjectRoot();
        var serveArgs = ServeArguments();
        var start = new ProcessStartInfo
        {
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            WorkingDirectory = WorkingDirectoryFor(jarvis, devRoot)
        };

        if (jarvis.EndsWith("uv.exe", StringComparison.OrdinalIgnoreCase))
        {
            if (string.IsNullOrEmpty(devRoot))
            {
                throw new InvalidOperationException(
                    "The OpenJarvis backend is not installed. Repair or reinstall OpenJarvis from Apps & Features.");
            }

            start.FileName = jarvis;
            start.Arguments = $"run --extra server --project {Quote(devRoot)} jarvis {serveArgs}";
        }
        else if (File.Exists(jarvis))
        {
            start.FileName = jarvis;
            start.Arguments = serveArgs;
        }
        else
        {
            throw new InvalidOperationException(
                "The OpenJarvis backend is not installed. Repair or reinstall OpenJarvis from Apps & Features.");
        }

        Directory.CreateDirectory(AppPaths.LogsDir);
        var log = Path.Combine(AppPaths.LogsDir, "jarvis-serve.log");
        File.AppendAllText(
            log,
            $"[{DateTimeOffset.Now:O}] {start.FileName} {start.Arguments} (cwd={start.WorkingDirectory}){Environment.NewLine}");
        start.Environment["OPENJARVIS_HOME"] = AppPaths.ConfigDir;
        _jarvis = Process.Start(start)
            ?? throw new InvalidOperationException("Failed to start jarvis serve.");
        _job.Add(_jarvis);
        _drain = DrainAsync(_jarvis, cancellationToken);
        await Task.Delay(500, cancellationToken);
    }

    private string ServeArguments()
    {
        return
            "serve --engine foundry_local " +
            $"--model {Quote(_settings.Current.SelectedModel)} " +
            "--agent simple " +
            "--port 8000 --host 127.0.0.1";
    }

    private static string WorkingDirectoryFor(string jarvis, string? devRoot)
    {
        if (!string.IsNullOrEmpty(devRoot) &&
            (jarvis.EndsWith("uv.exe", StringComparison.OrdinalIgnoreCase) ||
             jarvis.StartsWith(devRoot + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)))
        {
            return devRoot;
        }

        return Directory.Exists(AppPaths.SrcDir) ? AppPaths.SrcDir : AppPaths.LocalAppData;
    }

    private static string Quote(string value)
    {
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }

    private async Task<string> FormatExitAsync(Process process, CancellationToken cancellationToken)
    {
        if (_drain is not null)
        {
            await Task.WhenAny(_drain, Task.Delay(TimeSpan.FromSeconds(2), cancellationToken));
        }

        string tail;
        lock (_logGate)
        {
            tail = _recentOutput.Trim();
        }

        if (tail.Length > 500)
        {
            tail = tail[^500..];
        }

        var message = $"jarvis serve exited with code {process.ExitCode}.";
        return tail.Length == 0
            ? $"{message} Check {AppPaths.LogsDir}."
            : $"{message} {tail}";
    }

    private async Task WaitUntilReadyAsync(CancellationToken cancellationToken)
    {
        var deadline = DateTime.UtcNow.AddMinutes(3);
        while (DateTime.UtcNow < deadline && !cancellationToken.IsCancellationRequested)
        {
            if (await _api.IsEngineHealthyAsync(cancellationToken))
            {
                SetStatus(SetupStep.Done, "Ready", "OpenJarvis is ready.", false);
                return;
            }

            if (_jarvis is { HasExited: true })
            {
                throw new InvalidOperationException(await FormatExitAsync(_jarvis, cancellationToken));
            }

            await Task.Delay(500, cancellationToken);
        }

        throw new InvalidOperationException(
            "Timed out waiting for the OpenJarvis backend after a model or agent change.");
    }

    private async Task WaitUntilUnhealthyAsync(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            await Task.Delay(3000, cancellationToken);
            if (!await _api.IsHealthyAsync(cancellationToken))
            {
                SetStatus(SetupStep.Engine, "Recovering", "The backend stopped. Restarting…", false);
                return;
            }
        }
    }

    private void StopJarvis()
    {
        try
        {
            if (_jarvis is { HasExited: false })
            {
                _jarvis.Kill(entireProcessTree: true);
            }
        }
        catch
        {
            // Best effort.
        }

        _jarvis?.Dispose();
        _jarvis = null;
    }

    private async Task DrainAsync(Process process, CancellationToken cancellationToken)
    {
        try
        {
            var log = Path.Combine(AppPaths.LogsDir, "jarvis-serve.log");
            var gate = new SemaphoreSlim(1, 1);
            await using var writer = new StreamWriter(
                new FileStream(log, FileMode.Append, FileAccess.Write, FileShare.ReadWrite))
            {
                AutoFlush = true
            };

            async Task Pump(StreamReader reader)
            {
                while (!cancellationToken.IsCancellationRequested)
                {
                    var line = await reader.ReadLineAsync(cancellationToken);
                    if (line is null)
                    {
                        break;
                    }

                    lock (_logGate)
                    {
                        _recentOutput = string.IsNullOrEmpty(_recentOutput)
                            ? line
                            : _recentOutput + "\n" + line;
                        if (_recentOutput.Length > 4000)
                        {
                            _recentOutput = _recentOutput[^4000..];
                        }
                    }

                    await gate.WaitAsync(cancellationToken);
                    try
                    {
                        await writer.WriteLineAsync(line);
                    }
                    finally
                    {
                        gate.Release();
                    }
                }
            }

            await Task.WhenAll(Pump(process.StandardOutput), Pump(process.StandardError));
        }
        catch (OperationCanceledException)
        {
            // App shutdown.
        }
        catch
        {
            // Logging is best-effort.
        }
    }

    private void SetStatus(SetupStep step, string phase, string detail, bool failed)
    {
        Status.Step = step;
        Status.Phase = phase;
        Status.Detail = detail;
        Status.Ready = step == SetupStep.Done;
        Status.Failed = failed;
        StatusChanged?.Invoke(this, EventArgs.Empty);
    }

    private static string Actionable(string message)
    {
        if (message.Contains("Foundry Local is not installed", StringComparison.OrdinalIgnoreCase) ||
            message.Contains("foundry.exe was not found", StringComparison.OrdinalIgnoreCase))
        {
            return message + " Choose Retry to install Foundry Local automatically.";
        }

        if (message.Contains("Foundry", StringComparison.OrdinalIgnoreCase))
        {
            return message
                + " Choose Retry (use a *-generic-cpu model id on VMs without a GPU).";
        }

        if (message.Contains("jarvis", StringComparison.OrdinalIgnoreCase))
        {
            return message + " Reinstall OpenJarvis if the backend files are missing.";
        }

        return message;
    }
}
