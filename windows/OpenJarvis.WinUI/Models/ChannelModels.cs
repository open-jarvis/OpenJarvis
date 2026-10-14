using System.Text.Json;
using System.Text.Json.Serialization;

namespace OpenJarvis.WinUI.Models;

/// <summary>One row from <c>GET /v1/managed-agents/{id}/channels</c> or the
/// result of <c>POST .../channels</c>. <c>ChannelType</c> is one of
/// "slack", "sendblue", "imessage" (live-wired on bind — see
/// <c>agent_manager_routes.py:bind_channel</c>) or any other
/// <c>TOOL_CREDENTIALS</c> key (stored but inert until the backend
/// restarts and re-reads config.toml/credentials.toml).</summary>
public sealed class ChannelBinding
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("agent_id")]
    public string AgentId { get; set; } = "";

    [JsonPropertyName("channel_type")]
    public string ChannelType { get; set; } = "";

    [JsonPropertyName("config")]
    public Dictionary<string, JsonElement>? Config { get; set; }

    [JsonPropertyName("session_id")]
    public string SessionId { get; set; } = "";

    [JsonPropertyName("routing_mode")]
    public string RoutingMode { get; set; } = "auto";

    public bool IsLive => ChannelType is "slack" or "sendblue" or "imessage";
}

/// <summary><c>GET /v1/channels</c>.</summary>
public sealed class ChannelsListResponse
{
    [JsonPropertyName("channels")]
    public List<string> Channels { get; set; } = [];

    [JsonPropertyName("status")]
    public string Status { get; set; } = "not_configured";
}

/// <summary><c>POST /v1/channels/sendblue/verify</c>.</summary>
public sealed class SendBlueVerifyResult
{
    [JsonPropertyName("valid")]
    public bool Valid { get; set; }

    [JsonPropertyName("numbers")]
    public List<string> Numbers { get; set; } = [];
}

/// <summary>Channels that only save credentials and need a backend restart
/// to activate — mirrors a curated subset of <c>core/credentials.py</c>'s
/// <c>TOOL_CREDENTIALS</c> (excludes Slack and SendBlue, which hot-attach
/// instead; excludes non-channel tools like web_search/get_weather).</summary>
public static class OtherChannelCredentials
{
    public static readonly IReadOnlyList<(string ChannelType, string DisplayName, string[] Keys)> All =
    [
        ("telegram", "Telegram", ["TELEGRAM_BOT_TOKEN"]),
        ("discord", "Discord", ["DISCORD_BOT_TOKEN"]),
        ("email", "Email", ["EMAIL_USERNAME", "EMAIL_PASSWORD"]),
        ("whatsapp", "WhatsApp", ["WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID"]),
        ("signal", "Signal", ["SIGNAL_CLI_PATH"]),
        ("google_chat", "Google Chat", ["GOOGLE_CHAT_WEBHOOK_URL"]),
        ("teams", "Microsoft Teams", ["TEAMS_WEBHOOK_URL"]),
        ("matrix", "Matrix", ["MATRIX_HOMESERVER", "MATRIX_ACCESS_TOKEN"]),
        ("mastodon", "Mastodon", ["MASTODON_ACCESS_TOKEN", "MASTODON_API_BASE_URL"]),
        ("reddit", "Reddit", ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USERNAME", "REDDIT_PASSWORD"]),
    ];
}
