using System.ComponentModel;
using System.Text.Json.Serialization;

namespace OpenJarvis.WinUI.Models;

/// <summary>
/// One row of <c>GET /v1/connectors</c>. <c>AuthType</c> is one of
/// "local" (no credentials — Apple-local sources, Hacker News, RSS; just a
/// connect toggle), "filesystem" (a local path), "token"/"credentials"
/// (a secret textbox), or "oauth" (system-browser flow).
///
/// Implements <see cref="INotifyPropertyChanged"/> solely for
/// <see cref="SyncStatusLabel"/>: the page polls sync status on a timer and
/// writes it directly onto this property (bound with Mode=OneWay) rather
/// than looking up a named element inside a realized ItemsControl
/// DataTemplate via ContainerFromItem/FindName, which doesn't reliably
/// share the template's namescope.
/// </summary>
public class ConnectorSummary : INotifyPropertyChanged
{
    private string _syncStatusLabel = "";

    public event PropertyChangedEventHandler? PropertyChanged;

    [JsonPropertyName("connector_id")]
    public string ConnectorId { get; set; } = "";

    [JsonPropertyName("display_name")]
    public string DisplayName { get; set; } = "";

    [JsonPropertyName("auth_type")]
    public string AuthType { get; set; } = "local";

    [JsonPropertyName("connected")]
    public bool Connected { get; set; }

    [JsonPropertyName("chunks")]
    public int Chunks { get; set; }

    public bool IsOAuth => AuthType == "oauth";
    public bool IsFilesystem => AuthType == "filesystem";
    public bool IsToken => AuthType is "token" or "credentials";
    public bool IsLocal => AuthType == "local";

    public bool ShowOAuthForm => IsOAuth && !Connected;
    public bool ShowFilesystemForm => IsFilesystem && !Connected;
    public bool ShowTokenForm => IsToken && !Connected;
    public bool ShowLocalForm => IsLocal && !Connected;

    public string SyncStatusLabel
    {
        get => _syncStatusLabel;
        set
        {
            if (_syncStatusLabel == value) return;
            _syncStatusLabel = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(SyncStatusLabel)));
        }
    }
}

public sealed class OAuthSetupInfo
{
    [JsonPropertyName("provider")]
    public string Provider { get; set; } = "";

    [JsonPropertyName("setup_url")]
    public string? SetupUrl { get; set; }

    [JsonPropertyName("setup_hint")]
    public string? SetupHint { get; set; }

    [JsonPropertyName("has_credentials")]
    public bool HasCredentials { get; set; }
}

/// <summary>
/// <c>GET /v1/connectors/{id}</c>. Note: unlike the list row, the detail
/// response does not include <c>chunks</c> — it's just not sent, not zero.
/// </summary>
public sealed class ConnectorDetail : ConnectorSummary
{
    [JsonPropertyName("auth_url")]
    public string? AuthUrl { get; set; }

    [JsonPropertyName("mcp_tools")]
    public List<string> McpTools { get; set; } = [];

    [JsonPropertyName("oauth_setup")]
    public OAuthSetupInfo? OAuthSetup { get; set; }
}

public sealed class ConnectResult
{
    [JsonPropertyName("connector_id")]
    public string ConnectorId { get; set; } = "";

    [JsonPropertyName("connected")]
    public bool Connected { get; set; }

    [JsonPropertyName("status")]
    public string Status { get; set; } = "";
}

/// <summary><c>GET /v1/connectors/{id}/sync</c>. <c>state</c> is one of
/// "idle", "syncing", "stopping", or "error" (confirmed via the backend's
/// disconnect-race handling — a 409 on disconnect means "stopping").</summary>
public sealed class SyncStatus
{
    [JsonPropertyName("connector_id")]
    public string ConnectorId { get; set; } = "";

    [JsonPropertyName("state")]
    public string State { get; set; } = "idle";

    [JsonPropertyName("items_synced")]
    public int ItemsSynced { get; set; }

    [JsonPropertyName("items_total")]
    public int ItemsTotal { get; set; }

    [JsonPropertyName("last_sync")]
    public string? LastSync { get; set; }

    [JsonPropertyName("error")]
    public string? Error { get; set; }

    public bool IsSyncing => State == "syncing";

    public string StatusLabel => State switch
    {
        "syncing" when ItemsTotal > 0 => $"Syncing… {ItemsSynced}/{ItemsTotal}",
        "syncing" => $"Syncing… {ItemsSynced} items",
        "error" => Error is { Length: > 0 } ? $"Sync error: {Error}" : "Sync error",
        "stopping" => "Still disconnecting…",
        _ when LastSync is { Length: > 0 } => $"Indexed {ItemsSynced} items · last synced {LastSync}",
        _ => "Not synced yet"
    };
}
