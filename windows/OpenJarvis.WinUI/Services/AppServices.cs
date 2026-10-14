using System.Text.Json;

namespace OpenJarvis.WinUI.Services;

public sealed class AppServices
{
    public required SettingsStore Settings { get; init; }
    public required ConversationStore Conversations { get; init; }
    public required JarvisApiClient Api { get; init; }
    public required FoundryClient Foundry { get; init; }
    public required BackendSupervisor Supervisor { get; init; }
    public required UpdateChecker Updates { get; init; }
    public required LogService Logs { get; init; }
    public required SpeechService Speech { get; init; }
    public string UpdateManifestUrl { get; init; } = "";

    public static AppServices Create()
    {
        var settings = new SettingsStore();
        settings.Load();
        TryLoadAppSettings(settings);
        var conversations = new ConversationStore();
        conversations.Load();
        var api = new JarvisApiClient();
        api.SetBaseUrl(settings.Current.ApiUrl);
        var foundry = new FoundryClient();
        ApplyFoundryPins(foundry);
        var supervisor = new BackendSupervisor(api, foundry, settings);
        return new AppServices
        {
            Settings = settings,
            Conversations = conversations,
            Api = api,
            Foundry = foundry,
            Supervisor = supervisor,
            Updates = new UpdateChecker(),
            Logs = new LogService(supervisor),
            Speech = new SpeechService(),
            UpdateManifestUrl = ReadUpdateManifestUrl()
        };
    }

    private static void TryLoadAppSettings(SettingsStore settings)
    {
        try
        {
            var path = Path.Combine(AppContext.BaseDirectory, "appsettings.json");
            if (!File.Exists(path))
            {
                return;
            }

            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            var root = doc.RootElement;
            if (root.TryGetProperty("ApiUrl", out var api))
            {
                settings.Current.ApiUrl = api.GetString() ?? settings.Current.ApiUrl;
            }

            if (root.TryGetProperty("DefaultModel", out var model) &&
                string.IsNullOrWhiteSpace(settings.Current.SelectedModel))
            {
                settings.Current.SelectedModel = model.GetString() ?? settings.Current.SelectedModel;
            }
        }
        catch
        {
            // Packaged defaults are optional.
        }
    }

    private static void ApplyFoundryPins(FoundryClient foundry)
    {
        try
        {
            var path = Path.Combine(AppContext.BaseDirectory, "appsettings.json");
            if (!File.Exists(path))
            {
                return;
            }

            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            var root = doc.RootElement;
            if (root.TryGetProperty("FoundryVersion", out var version) &&
                version.GetString() is { Length: > 0 } v)
            {
                foundry.Version = v;
            }

            if (root.TryGetProperty("FoundryReleaseTag", out var tag) &&
                tag.GetString() is { Length: > 0 } t)
            {
                foundry.ReleaseTag = t;
            }
        }
        catch
        {
            // Optional pins.
        }
    }

    public static string ReadUpdateManifestUrl()
    {
        try
        {
            var path = Path.Combine(AppContext.BaseDirectory, "appsettings.json");
            if (!File.Exists(path))
            {
                return "";
            }

            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            if (doc.RootElement.TryGetProperty("UpdateManifestUrl", out var url))
            {
                return url.GetString() ?? "";
            }
        }
        catch
        {
            // Optional.
        }

        return "";
    }
}
