using System.Diagnostics;
using System.Reflection;
using System.Text.Json;

namespace OpenJarvis.WinUI.Services;

public sealed class UpdateInfo
{
    public string Version { get; set; } = "";
    public string Url { get; set; } = "";
    public string Notes { get; set; } = "";
}

public sealed class UpdateChecker
{
    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(15) };

    public async Task<UpdateInfo?> CheckAsync(string manifestUrl, CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(manifestUrl))
        {
            return null;
        }

        try
        {
            using var response = await _http.GetAsync(manifestUrl, cancellationToken);
            if (!response.IsSuccessStatusCode)
            {
                return null;
            }

            var info = await JsonSerializer.DeserializeAsync<UpdateInfo>(
                await response.Content.ReadAsStreamAsync(cancellationToken),
                new JsonSerializerOptions { PropertyNameCaseInsensitive = true },
                cancellationToken);
            if (info is null || string.IsNullOrWhiteSpace(info.Version))
            {
                return null;
            }

            var current = Assembly.GetExecutingAssembly().GetName().Version ?? new Version(1, 0, 0, 0);
            if (Version.TryParse(info.Version.TrimStart('v'), out var remote) && remote > current)
            {
                return info;
            }
        }
        catch
        {
            return null;
        }

        return null;
    }

    public static void LaunchInstaller(string url)
    {
        Process.Start(new ProcessStartInfo
        {
            FileName = url,
            UseShellExecute = true
        });
    }
}
