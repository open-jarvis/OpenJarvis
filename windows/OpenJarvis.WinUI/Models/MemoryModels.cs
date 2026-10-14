using System.Text.Json;
using System.Text.Json.Serialization;

namespace OpenJarvis.WinUI.Models;

/// <summary><c>GET /v1/memory/stats</c>.</summary>
public sealed class MemoryStats
{
    [JsonPropertyName("entries")]
    public int Entries { get; set; }

    [JsonPropertyName("backend")]
    public string Backend { get; set; } = "none";

    [JsonPropertyName("status")]
    public string? Status { get; set; }
}

/// <summary>One row of <c>POST /v1/memory/search</c>'s <c>results</c> array.</summary>
public sealed class MemorySearchResult
{
    [JsonPropertyName("content")]
    public string Content { get; set; } = "";

    [JsonPropertyName("score")]
    public double Score { get; set; }

    [JsonPropertyName("metadata")]
    public Dictionary<string, JsonElement>? Metadata { get; set; }

    public string? Source =>
        Metadata is not null &&
        Metadata.TryGetValue("source", out var value) &&
        value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    public bool HasSource => !string.IsNullOrEmpty(Source);

    public string ScoreLabel => $"{Score:P0} match";

    /// <summary>Resource key for <see cref="OpenJarvis.WinUI.Converters.StatusBrushConverter"/>,
    /// matching React's green/amber/gray match-badge thresholds (&gt;0.5 / &gt;0.2 / else).</summary>
    public string ScoreBrushKey => Score switch
    {
        > 0.5 => "StatusSuccessBrush",
        > 0.2 => "StatusPausedBrush",
        _ => "StatusIdleBrush"
    };
}

/// <summary><c>GET /v1/memory/config</c>. Read-only — there is no matching
/// write endpoint; saved values go through <c>config.toml</c> instead and
/// need a backend restart to take effect.</summary>
public sealed class MemoryConfigInfo
{
    [JsonPropertyName("backend_type")]
    public string BackendType { get; set; } = "sqlite";

    [JsonPropertyName("available")]
    public bool Available { get; set; }

    [JsonPropertyName("detail")]
    public string? Detail { get; set; }

    [JsonPropertyName("context_top_k")]
    public int ContextTopK { get; set; } = 5;

    [JsonPropertyName("context_min_score")]
    public double ContextMinScore { get; set; } = 0.1;

    [JsonPropertyName("context_max_tokens")]
    public int ContextMaxTokens { get; set; } = 2048;

    [JsonPropertyName("context_from_memory")]
    public bool ContextFromMemory { get; set; } = true;
}

/// <summary><c>POST /v1/memory/index</c>.</summary>
public sealed class MemoryIndexResult
{
    [JsonPropertyName("status")]
    public string Status { get; set; } = "";

    [JsonPropertyName("chunks_indexed")]
    public int ChunksIndexed { get; set; }

    [JsonPropertyName("note")]
    public string? Note { get; set; }
}
