using System.Diagnostics;
using System.Net.Http;
using System.Text.Json;
using System.Text.RegularExpressions;
using OpenJarvis.WinUI.Models;

namespace OpenJarvis.WinUI.Services;

/// <summary>
/// Talks to the Foundry Local CLI. Current preview builds use
/// <c>foundry server …</c> and <c>foundry model load</c>; older builds used
/// <c>service</c> / <c>model run</c>. We try the new verbs first, then fall back.
/// When Foundry is missing, Setup downloads the ARM64 MSIX and installs it via
/// <c>Add-AppxPackage</c> (no terminal required).
/// </summary>
public sealed class FoundryClient
{
    private static readonly HttpClient Http = new() { Timeout = TimeSpan.FromMinutes(30) };

    public event EventHandler<string>? Progress;

    public string Version { get; set; } = "0.11.0";
    public string ReleaseTag { get; set; } = "cli-preview-0.11.0";

    public string? FindFoundry()
    {
        var onPath = AppPaths.FindOnPath("foundry.exe");
        if (onPath is not null && File.Exists(onPath))
        {
            return onPath;
        }

        var windowsApps = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Microsoft", "WindowsApps", "foundry.exe");
        if (File.Exists(windowsApps))
        {
            return windowsApps;
        }

        var winget = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Microsoft", "WinGet", "Links", "foundry.exe");
        if (File.Exists(winget))
        {
            return winget;
        }

        try
        {
            var appsRoot = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
                "WindowsApps");
            if (Directory.Exists(appsRoot))
            {
                foreach (var dir in Directory.EnumerateDirectories(appsRoot, "Microsoft.FoundryLocal_*"))
                {
                    var candidate = Path.Combine(dir, "foundry.exe");
                    if (File.Exists(candidate))
                    {
                        return candidate;
                    }
                }
            }
        }
        catch
        {
            // WindowsApps enumeration can fail without admin; ignore.
        }

        return null;
    }

    /// <summary>
    /// Ensures Foundry Local is installed (download + Add-AppxPackage if needed),
    /// then starts the server and returns the OpenAI-compatible base URL.
    /// </summary>
    public async Task<string> EnsureServiceAsync(
        CancellationToken cancellationToken,
        IProgress<string>? progress = null)
    {
        await EnsureInstalledAsync(cancellationToken, progress);

        var foundry = FindFoundry()
            ?? throw new InvalidOperationException(
                "Foundry Local installed but foundry.exe was not found. Sign out and back in, or reopen OpenJarvis.");

        Report(progress, "Starting Foundry Local…");
        await RunFirstSuccessAsync(
            foundry,
            new[] { "server start", "service start" },
            cancellationToken,
            "Could not start Foundry Local. Choose Retry to try again.",
            progress);
        var host = await DiscoverHostAsync(foundry, cancellationToken);
        TomlSettings.SetFoundryHost(host);
        TomlSettings.SetEngineDefault("foundry_local");
        return host;
    }

    public async Task EnsureInstalledAsync(
        CancellationToken cancellationToken,
        IProgress<string>? progress = null)
    {
        if (FindFoundry() is not null)
        {
            Report(progress, "Foundry Local is already installed.");
            return;
        }

        Report(progress, $"Downloading Foundry Local {Version} (ARM64)…");
        Directory.CreateDirectory(AppPaths.RuntimeDir);
        var msixPath = await DownloadMsixAsync(cancellationToken, progress);

        Report(progress, "Installing Foundry Local…");
        await InstallMsixAsync(msixPath, cancellationToken, progress);

        // App execution aliases can take a moment to appear.
        for (var i = 0; i < 20; i++)
        {
            if (FindFoundry() is not null)
            {
                Report(progress, "Foundry Local is ready.");
                return;
            }

            await Task.Delay(500, cancellationToken);
        }

        throw new InvalidOperationException(
            "Foundry Local MSIX installed but foundry.exe is not on PATH yet. Close and reopen OpenJarvis, then continue Setup.");
    }

    public async Task DownloadModelAsync(
        string alias,
        IProgress<string>? progress,
        CancellationToken cancellationToken)
    {
        await EnsureInstalledAsync(cancellationToken, progress);
        var foundry = FindFoundry()
            ?? throw new InvalidOperationException("Foundry Local is not installed.");
        progress?.Report($"Downloading model {alias}…");
        await RunAsync(foundry, $"model download {QuoteModel(alias)}", cancellationToken, progress);
        progress?.Report($"Loading model {alias}…");
        await LoadModelAsync(foundry, alias, cancellationToken, progress);
    }

    /// <summary>
    /// Foundry keeps catalog files on disk, but inference returns HTTP 400 until
    /// <c>foundry model load</c> brings that variant into the running daemon.
    /// </summary>
    public async Task<string> EnsureModelLoadedAsync(
        string model,
        CancellationToken cancellationToken,
        IProgress<string>? progress = null)
    {
        if (string.IsNullOrWhiteSpace(model))
        {
            return model;
        }

        if (await IsModelLoadedAsync(model, cancellationToken))
        {
            progress?.Report($"Model {model} is already loaded.");
            return model;
        }

        await EnsureInstalledAsync(cancellationToken, progress);
        var foundry = FindFoundry()
            ?? throw new InvalidOperationException("Foundry Local is not installed.");

        progress?.Report($"Loading model {model}…");
        try
        {
            await LoadOrDownloadAsync(foundry, model, cancellationToken, progress);
        }
        catch (InvalidOperationException ex) when (
            CpuCatalogId(model) is string cpu && IsGpuLoadFailure(ex.Message))
        {
            progress?.Report(
                $"GPU/WebGPU could not load {model}. Loading {cpu} instead…");
            await LoadOrDownloadAsync(foundry, cpu, cancellationToken, progress);
            return cpu;
        }

        return model;
    }

    /// <summary>
    /// Map a versioned GPU catalog id onto the matching CPU id.
    /// <c>gemma-4-e2b-it-generic-gpu:3</c> becomes <c>gemma-4-e2b-it-generic-cpu:3</c>.
    /// </summary>
    public static string? CpuCatalogId(string model)
    {
        const string gpu = "generic-gpu";
        if (string.IsNullOrWhiteSpace(model) ||
            model.Contains("generic-cpu", StringComparison.OrdinalIgnoreCase))
        {
            return null;
        }

        var index = model.IndexOf(gpu, StringComparison.OrdinalIgnoreCase);
        if (index < 0)
        {
            return null;
        }

        return string.Concat(
            model.AsSpan(0, index),
            "generic-cpu",
            model.AsSpan(index + gpu.Length));
    }

    public async Task<bool> IsModelLoadedAsync(string model, CancellationToken cancellationToken)
    {
        var foundry = FindFoundry();
        if (foundry is null || string.IsNullOrWhiteSpace(model))
        {
            return false;
        }

        var (stdout, _) = await RunCaptureAsync(
            foundry,
            "model list --loaded --variants -o json",
            cancellationToken);
        var jsonStart = stdout.IndexOf('{');
        if (jsonStart < 0)
        {
            return false;
        }

        try
        {
            using var doc = JsonDocument.Parse(stdout[jsonStart..]);
            if (!doc.RootElement.TryGetProperty("variants", out var variants) ||
                variants.ValueKind != JsonValueKind.Array)
            {
                return false;
            }

            foreach (var variant in variants.EnumerateArray())
            {
                if (VariantMatches(model, variant))
                {
                    return true;
                }
            }
        }
        catch (JsonException)
        {
            return false;
        }

        return false;
    }

    /// <summary>
    /// Split Foundry variants into downloaded (installed) vs catalog-only (downloadable).
    /// </summary>
    public async Task<FoundryModelCatalog> ListCatalogAsync(CancellationToken cancellationToken)
    {
        var foundry = FindFoundry();
        if (foundry is null)
        {
            return new FoundryModelCatalog();
        }

        var (stdout, _) = await RunCaptureAsync(
            foundry,
            "model list --variants -o json",
            cancellationToken);
        var jsonStart = stdout.IndexOf('{');
        if (jsonStart < 0)
        {
            return new FoundryModelCatalog();
        }

        try
        {
            using var doc = JsonDocument.Parse(stdout[jsonStart..]);
            if (!doc.RootElement.TryGetProperty("variants", out var variants) ||
                variants.ValueKind != JsonValueKind.Array)
            {
                return new FoundryModelCatalog();
            }

            var installed = new List<string>();
            var available = new List<string>();
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var variant in variants.EnumerateArray())
            {
                var id = ReadString(variant, "variantId")
                    ?? ReadString(variant, "variantName")
                    ?? ReadString(variant, "alias");
                if (string.IsNullOrWhiteSpace(id) || !seen.Add(id))
                {
                    continue;
                }

                var cached = variant.TryGetProperty("cached", out var cachedEl) &&
                             cachedEl.ValueKind is JsonValueKind.True;
                if (cached)
                {
                    installed.Add(id);
                }
                else
                {
                    available.Add(id);
                }
            }

            return new FoundryModelCatalog
            {
                Installed = installed,
                Available = available
            };
        }
        catch (JsonException)
        {
            return new FoundryModelCatalog();
        }
    }

    private static async Task LoadModelAsync(
        string foundry,
        string model,
        CancellationToken cancellationToken,
        IProgress<string>? progress)
    {
        var arg = QuoteModel(model);
        await RunFirstSuccessAsync(
            foundry,
            new[] { $"model load {arg}", $"model run {arg} --skip-chat" },
            cancellationToken,
            $"Could not load model {model}. On VMs without a GPU, use a *-generic-cpu catalog id.",
            progress);
    }

    private static bool VariantMatches(string requested, JsonElement variant)
    {
        var id = ReadString(variant, "variantId");
        var name = ReadString(variant, "variantName");
        var alias = ReadString(variant, "alias");
        if (string.Equals(id, requested, StringComparison.OrdinalIgnoreCase) ||
            string.Equals(name, requested, StringComparison.OrdinalIgnoreCase) ||
            string.Equals(alias, requested, StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        return !requested.Contains(':') &&
               id is not null &&
               id.StartsWith(requested + "-", StringComparison.OrdinalIgnoreCase);
    }

    private static string? ReadString(JsonElement element, string name)
    {
        return element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;
    }

    private static string QuoteModel(string model)
    {
        if (model.IndexOfAny([' ', '\t', '"']) < 0)
        {
            return model;
        }

        return "\"" + model.Replace("\"", "") + "\"";
    }

    private async Task LoadOrDownloadAsync(
        string foundry,
        string model,
        CancellationToken cancellationToken,
        IProgress<string>? progress)
    {
        try
        {
            await LoadModelAsync(foundry, model, cancellationToken, progress);
        }
        catch (InvalidOperationException ex) when (IsNotCached(ex.Message))
        {
            progress?.Report($"Model {model} is not in the local cache. Downloading…");
            await DownloadModelAsync(model, progress, cancellationToken);
        }
    }

    private static bool IsGpuLoadFailure(string message)
    {
        return message.Contains("WebGPU", StringComparison.OrdinalIgnoreCase) ||
               message.Contains("EP_FAIL", StringComparison.OrdinalIgnoreCase) ||
               message.Contains("execution provider", StringComparison.OrdinalIgnoreCase) ||
               message.Contains("d3dcompiler", StringComparison.OrdinalIgnoreCase) ||
               (message.Contains("Failed to get a", StringComparison.OrdinalIgnoreCase) &&
                message.Contains("device", StringComparison.OrdinalIgnoreCase));
    }

    private static bool IsNotCached(string message)
    {
        return message.Contains("not cached", StringComparison.OrdinalIgnoreCase) ||
               message.Contains("not downloaded", StringComparison.OrdinalIgnoreCase) ||
               message.Contains("download the model", StringComparison.OrdinalIgnoreCase) ||
               message.Contains("model not found", StringComparison.OrdinalIgnoreCase);
    }

    public async Task<string> DiscoverHostAsync(string foundry, CancellationToken cancellationToken)
    {
        foreach (var arguments in new[]
                 {
                     "server status --json",
                     "server status",
                     "service status --json",
                     "service status",
                 })
        {
            var (stdout, stderr) = await RunCaptureAsync(foundry, arguments, cancellationToken);
            var match = Regex.Match(stdout + "\n" + stderr, @"https?://[^\s""']+");
            if (match.Success)
            {
                return NormalizeFoundryBase(match.Value);
            }
        }

        throw new InvalidOperationException(
            "Foundry Local started but did not report an endpoint. Choose Retry to try again.");
    }

    private async Task<string> DownloadMsixAsync(
        CancellationToken cancellationToken,
        IProgress<string>? progress)
    {
        var assetNames = new[]
        {
            $"foundry-{Version}-win-arm64-winml.msix",
            $"foundry-{Version}-win-arm64.msix",
        };

        Exception? last = null;
        foreach (var asset in assetNames)
        {
            var url =
                $"https://github.com/microsoft/Foundry-Local/releases/download/{ReleaseTag}/{asset}";
            var dest = Path.Combine(AppPaths.RuntimeDir, asset);
            try
            {
                Report(progress, $"Fetching {asset}…");
                await using var remote = await Http.GetStreamAsync(url, cancellationToken);
                await using var file = File.Create(dest);
                await remote.CopyToAsync(file, cancellationToken);
                if (new FileInfo(dest).Length < 1_000_000)
                {
                    throw new InvalidOperationException($"Download of {asset} looks incomplete.");
                }

                return dest;
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                last = ex;
                try
                {
                    if (File.Exists(dest))
                    {
                        File.Delete(dest);
                    }
                }
                catch
                {
                    // ignore
                }
            }
        }

        throw new InvalidOperationException(
            $"Could not download Foundry Local {Version} for ARM64. Check your network and choose Retry. "
            + (last?.Message ?? ""),
            last);
    }

    private static async Task InstallMsixAsync(
        string msixPath,
        CancellationToken cancellationToken,
        IProgress<string>? progress)
    {
        // Add-AppxPackage works for current user without an elevated terminal when the
        // package is signed by Microsoft (Foundry Local releases).
        var psi = new ProcessStartInfo
        {
            FileName = "powershell.exe",
            Arguments =
                $"-NoProfile -ExecutionPolicy Bypass -Command \"Add-AppxPackage -Path '{msixPath.Replace("'", "''")}'\"",
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true
        };
        using var process = Process.Start(psi)
            ?? throw new InvalidOperationException("Failed to start PowerShell to install Foundry Local.");
        var stdout = await process.StandardOutput.ReadToEndAsync(cancellationToken);
        var stderr = await process.StandardError.ReadToEndAsync(cancellationToken);
        await process.WaitForExitAsync(cancellationToken);
        if (!string.IsNullOrWhiteSpace(stdout))
        {
            progress?.Report(stdout.Trim());
        }

        if (process.ExitCode != 0)
        {
            throw new InvalidOperationException(
                "Installing Foundry Local failed. "
                + (string.IsNullOrWhiteSpace(stderr) ? stdout : stderr).Trim());
        }
    }

    private static string NormalizeFoundryBase(string url)
    {
        url = url.TrimEnd('/');
        foreach (var suffix in new[] { "/openai/status", "/openai", "/v1" })
        {
            if (url.EndsWith(suffix, StringComparison.OrdinalIgnoreCase))
            {
                return url[..^suffix.Length];
            }
        }

        return url;
    }

    private void Report(IProgress<string>? progress, string message)
    {
        Progress?.Invoke(this, message);
        progress?.Report(message);
    }

    private static async Task RunFirstSuccessAsync(
        string fileName,
        IReadOnlyList<string> argumentVariants,
        CancellationToken cancellationToken,
        string failureMessage,
        IProgress<string>? progress = null)
    {
        Exception? last = null;
        foreach (var arguments in argumentVariants)
        {
            try
            {
                await RunAsync(fileName, arguments, cancellationToken, progress);
                return;
            }
            catch (InvalidOperationException ex)
            {
                last = ex;
            }
        }

        throw new InvalidOperationException(
            failureMessage + (last is null ? "" : " " + last.Message),
            last);
    }

    private static async Task RunAsync(
        string fileName,
        string arguments,
        CancellationToken cancellationToken,
        IProgress<string>? progress = null)
    {
        var start = new ProcessStartInfo
        {
            FileName = fileName,
            Arguments = arguments,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true
        };
        using var process = Process.Start(start)
            ?? throw new InvalidOperationException($"Failed to start {fileName}.");
        var tail = "";
        void Remember(string? line)
        {
            if (string.IsNullOrWhiteSpace(line))
            {
                return;
            }

            progress?.Report(line);
            lock (start)
            {
                tail = string.IsNullOrEmpty(tail) ? line.Trim() : tail + " " + line.Trim();
                if (tail.Length > 600)
                {
                    tail = tail[^600..];
                }
            }
        }

        process.OutputDataReceived += (_, e) => Remember(e.Data);
        process.ErrorDataReceived += (_, e) => Remember(e.Data);
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        await WaitOrKillAsync(process, cancellationToken);
        process.WaitForExit();
        if (process.ExitCode != 0)
        {
            var detail = tail.Trim();
            throw new InvalidOperationException(
                $"Foundry command `{arguments}` failed with exit {process.ExitCode}."
                + (detail.Length == 0 ? "" : " " + detail));
        }
    }

    private static async Task<(string Stdout, string Stderr)> RunCaptureAsync(
        string fileName,
        string arguments,
        CancellationToken cancellationToken)
    {
        var start = new ProcessStartInfo
        {
            FileName = fileName,
            Arguments = arguments,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true
        };
        using var process = Process.Start(start)
            ?? throw new InvalidOperationException($"Failed to start {fileName}.");
        try
        {
            var stdout = await process.StandardOutput.ReadToEndAsync(cancellationToken);
            var stderr = await process.StandardError.ReadToEndAsync(cancellationToken);
            await process.WaitForExitAsync(cancellationToken);
            return (stdout, stderr);
        }
        catch (OperationCanceledException)
        {
            Kill(process);
            throw;
        }
    }

    /// <summary>
    /// Cancelling setup must not leave a multi-gigabyte <c>foundry model download</c> running.
    /// </summary>
    private static async Task WaitOrKillAsync(Process process, CancellationToken cancellationToken)
    {
        try
        {
            await process.WaitForExitAsync(cancellationToken);
        }
        catch (OperationCanceledException)
        {
            Kill(process);
            throw;
        }
    }

    private static void Kill(Process process)
    {
        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
            }
        }
        catch
        {
            // Best effort.
        }
    }
}
