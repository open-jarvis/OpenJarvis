using System.ComponentModel;
using System.Text.Json.Serialization;

namespace OpenJarvis.WinUI.Models;

/// <summary>One row of <c>CloudModelsPanel</c>'s provider list — mutable
/// view-model wrapper over <see cref="CloudProviderKey"/> so the
/// "Connected" indicator and Remove button can update after a save.</summary>
public sealed class CloudKeyRow : INotifyPropertyChanged
{
    private bool _isConnected;

    public event PropertyChangedEventHandler? PropertyChanged;

    public required string ProviderName { get; init; }
    public required string EnvVarName { get; init; }

    public bool IsConnected
    {
        get => _isConnected;
        set
        {
            if (_isConnected == value) return;
            _isConnected = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(IsConnected)));
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(PlaceholderText)));
        }
    }

    public string PlaceholderText => IsConnected ? "Saved to your local profile" : EnvVarName;
}

/// <summary><c>POST /v1/cloud/reload</c>. <c>Status</c> is "ok", "no_cloud"
/// (constructed engine failed its health check — likely a bad key), or
/// "error" (constructor threw).</summary>
public sealed class CloudReloadResult
{
    [JsonPropertyName("status")]
    public string Status { get; set; } = "";

    [JsonPropertyName("message")]
    public string? Message { get; set; }
}

/// <summary>One cloud inference provider whose API key is stored in
/// <c>cloud-keys.env</c> and hot-reloaded via <c>POST /v1/cloud/reload</c>.
/// Distinct from tool/channel credentials (Tavily, Slack, etc.), which go
/// through <c>/v1/tools/{tool}/credentials</c> and <c>credentials.toml</c>
/// instead — see <see cref="CloudProviderKey.All"/> vs. that other path.</summary>
public sealed class CloudProviderKey
{
    public required string ProviderName { get; init; }
    public required string EnvVarName { get; init; }

    public static readonly IReadOnlyList<CloudProviderKey> All =
    [
        new() { ProviderName = "OpenAI", EnvVarName = "OPENAI_API_KEY" },
        new() { ProviderName = "Anthropic", EnvVarName = "ANTHROPIC_API_KEY" },
        new() { ProviderName = "Google", EnvVarName = "GEMINI_API_KEY" },
        new() { ProviderName = "OpenRouter", EnvVarName = "OPENROUTER_API_KEY" },
        new() { ProviderName = "Atlas Cloud", EnvVarName = "ATLASCLOUD_API_KEY" },
        new() { ProviderName = "Minimax", EnvVarName = "MINIMAX_API_KEY" },
    ];
}
