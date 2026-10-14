using System.Text.Json;
using System.Text.Json.Serialization;

namespace OpenJarvis.WinUI.Models;

/// <summary>
/// <c>GET /v1/telemetry/stats</c> — session-aggregate counters from
/// <c>telemetry.db</c>. Fails soft: a fresh/empty database returns this
/// shape with every field zeroed, not an HTTP error — treat zero as
/// "no data yet", not a fetch failure.
/// </summary>
public sealed class TelemetryStats
{
    [JsonPropertyName("total_tokens")]
    public long TotalTokens { get; set; }

    [JsonPropertyName("total_cost")]
    public double TotalCost { get; set; }

    [JsonPropertyName("total_requests")]
    public long TotalRequests { get; set; }

    [JsonPropertyName("avg_throughput_tok_per_sec")]
    public double AvgThroughputTokPerSec { get; set; }
}

/// <summary>
/// <c>GET /v1/telemetry/energy</c>. Temps are confirmed always <c>null</c>
/// today (not wired on this hardware) — nullable, not a default of 0.
/// </summary>
public sealed class EnergyStats
{
    [JsonPropertyName("total_energy_j")]
    public double TotalEnergyJ { get; set; }

    [JsonPropertyName("energy_per_token_j")]
    public double EnergyPerTokenJ { get; set; }

    [JsonPropertyName("avg_power_w")]
    public double AvgPowerW { get; set; }

    [JsonPropertyName("cpu_temp_c")]
    public double? CpuTempC { get; set; }

    [JsonPropertyName("gpu_temp_c")]
    public double? GpuTempC { get; set; }

    /// <summary>Cool/Warm/Hot, matching React's EnergyDashboard thresholds.</summary>
    public string ThermalLabel => AvgPowerW switch
    {
        <= 0 => "—",
        < 15 => "Cool",
        < 35 => "Warm",
        _ => "Hot"
    };
}

public sealed class SavingsProvider
{
    [JsonPropertyName("provider")]
    public string Provider { get; set; } = "";

    [JsonPropertyName("label")]
    public string Label { get; set; } = "";

    [JsonPropertyName("total_cost")]
    public double TotalCost { get; set; }

    public string CostLabel => $"${TotalCost:0.0000}";
}

/// <summary>Display-ready label/value pair for a Dashboard stat tile — kept
/// as plain strings (not the raw numeric telemetry) so the page's
/// code-behind owns unit formatting/rounding in one place.</summary>
public sealed class StatTile
{
    public string Label { get; init; } = "";
    public string Value { get; init; } = "";
}

/// <summary>
/// <c>GET /v1/savings</c> — local cost vs. 3 reference cloud providers,
/// session-scoped (since <c>session_start_ts</c>). Not polled; this is a
/// point-in-time comparison, same as React's CostComparison.
/// </summary>
public sealed class SavingsInfo
{
    [JsonPropertyName("total_calls")]
    public long TotalCalls { get; set; }

    [JsonPropertyName("total_tokens")]
    public long TotalTokens { get; set; }

    [JsonPropertyName("local_cost")]
    public double LocalCost { get; set; }

    [JsonPropertyName("per_provider")]
    public List<SavingsProvider> PerProvider { get; set; } = [];
}

public sealed class TraceStep
{
    [JsonPropertyName("step_type")]
    public string StepType { get; set; } = "";

    [JsonPropertyName("duration_seconds")]
    public double DurationSeconds { get; set; }

    [JsonPropertyName("output")]
    public JsonElement Output { get; set; }

    public string DurationLabel => DurationSeconds >= 1
        ? $"{DurationSeconds:0.0}s"
        : $"{DurationSeconds * 1000:0}ms";

    /// <summary>Best-effort one-line summary of this step's <c>output</c>
    /// (varies by <see cref="StepType"/> — "generate" has a "content"
    /// string, "respond" too; anything else falls back to the step type).</summary>
    public string OutputPreview
    {
        get
        {
            if (Output.ValueKind == JsonValueKind.Object &&
                Output.TryGetProperty("content", out var content) &&
                content.ValueKind == JsonValueKind.String)
            {
                var text = content.GetString() ?? "";
                return text.Length > 120 ? text[..120] + "…" : text;
            }

            return StepType;
        }
    }
}

/// <summary>
/// One recent agent run. <c>query</c> is the original user message — used
/// as the list-row label, matching TraceDebugger.tsx. The full
/// <c>messages</c> transcript the backend also returns is intentionally not
/// modeled here; the trace step list is what the detail pane shows.
/// </summary>
public sealed class TraceSummary
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("query")]
    public string Query { get; set; } = "";

    [JsonPropertyName("agent")]
    public string Agent { get; set; } = "";

    [JsonPropertyName("created_at")]
    public string CreatedAt { get; set; } = "";

    [JsonPropertyName("duration_ms")]
    public long DurationMs { get; set; }

    [JsonPropertyName("total_tokens")]
    public long TotalTokens { get; set; }

    [JsonPropertyName("steps")]
    public List<TraceStep> Steps { get; set; } = [];

    public string DurationLabel => DurationMs >= 1000
        ? $"{DurationMs / 1000.0:0.0}s"
        : $"{DurationMs}ms";
}

public sealed class TracesResponse
{
    [JsonPropertyName("traces")]
    public List<TraceSummary> Traces { get; set; } = [];
}
