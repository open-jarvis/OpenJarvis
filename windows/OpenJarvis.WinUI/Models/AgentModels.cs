using System.ComponentModel;
using System.Text.Json.Serialization;

namespace OpenJarvis.WinUI.Models;

/// <summary>Loosely-typed agent config — the backend accepts/returns a free-form
/// object here (confirmed live: a created agent's <c>config</c> only contains
/// the fields actually set), so every field is optional.</summary>
public sealed class AgentConfig
{
    [JsonPropertyName("instruction")]
    public string? Instruction { get; set; }

    [JsonPropertyName("tools")]
    public List<string> Tools { get; set; } = [];

    [JsonPropertyName("model")]
    public string? Model { get; set; }

    [JsonPropertyName("schedule_type")]
    public string ScheduleType { get; set; } = "manual";

    [JsonPropertyName("schedule_value")]
    public string? ScheduleValue { get; set; }

    [JsonPropertyName("max_turns")]
    public int? MaxTurns { get; set; }

    [JsonPropertyName("temperature")]
    public double? Temperature { get; set; }

    [JsonPropertyName("memory_extraction")]
    public string? MemoryExtraction { get; set; }

    [JsonPropertyName("observation_compression")]
    public string? ObservationCompression { get; set; }

    [JsonPropertyName("retrieval_strategy")]
    public string? RetrievalStrategy { get; set; }

    [JsonPropertyName("task_decomposition")]
    public string? TaskDecomposition { get; set; }

    [JsonPropertyName("budget")]
    public double? Budget { get; set; }

    public string ScheduleLabel => ScheduleType switch
    {
        "daily" => "Daily",
        "weekly" => "Weekly",
        "hourly" => "Hourly",
        "interval" => ScheduleValue is { Length: > 0 } ? $"Every {ScheduleValue}s" : "Interval",
        "cron" => ScheduleValue is { Length: > 0 } ? $"Cron: {ScheduleValue}" : "Cron",
        _ => "Manual"
    };
}

/// <summary>One row of <c>GET /v1/managed-agents</c>. Implements
/// <see cref="INotifyPropertyChanged"/> so the list page can refresh a row's
/// status/cost in place on each poll tick without losing scroll position or
/// selection, matching the pattern already used for live tool-activity and
/// connector sync status.</summary>
public class ManagedAgentSummary : INotifyPropertyChanged
{
    private string _status = "idle";
    private double _totalCost;
    private long _totalRuns;
    private string _currentActivity = "";

    public event PropertyChangedEventHandler? PropertyChanged;

    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    [JsonPropertyName("agent_type")]
    public string AgentType { get; set; } = "";

    [JsonPropertyName("config")]
    public AgentConfig Config { get; set; } = new();

    [JsonPropertyName("status")]
    public string Status
    {
        get => _status;
        set { if (_status == value) return; _status = value; Raise(); Raise(nameof(StatusBrushKey)); }
    }

    [JsonPropertyName("total_cost")]
    public double TotalCost
    {
        get => _totalCost;
        set
        {
            if (_totalCost == value) return;
            _totalCost = value;
            Raise();
            Raise(nameof(CostLabel));
            Raise(nameof(BudgetFractionValue));
            Raise(nameof(BudgetBrushKey));
        }
    }

    [JsonPropertyName("total_runs")]
    public long TotalRuns
    {
        get => _totalRuns;
        set { if (_totalRuns == value) return; _totalRuns = value; Raise(); }
    }

    [JsonPropertyName("last_run_at")]
    public double? LastRunAt { get; set; }

    [JsonPropertyName("current_activity")]
    public string CurrentActivity
    {
        get => _currentActivity;
        set { if (_currentActivity == value) return; _currentActivity = value ?? ""; Raise(); }
    }

    [JsonPropertyName("summary_memory")]
    public string SummaryMemory { get; set; } = "";

    public string StatusBrushKey => Status switch
    {
        "running" => "StatusRunningBrush",
        "paused" => "StatusPausedBrush",
        "error" or "stalled" or "budget_exceeded" or "needs_attention" => "StatusErrorBrush",
        "idle" => "StatusSuccessBrush",
        _ => "StatusIdleBrush"
    };

    public string CostLabel => $"${TotalCost:0.0000}";

    public string LastRunLabel => LastRunAt is { } ts
        ? FormatRelative(DateTimeOffset.FromUnixTimeSeconds((long)ts))
        : "Never";

    public bool CanRun => Status is "idle" or "error" or "stalled";
    public bool CanPause => Status is "running" or "idle";
    public bool CanResume => Status == "paused";
    public bool CanRecover => Status is "error" or "stalled" or "needs_attention" or "budget_exceeded";

    public bool HasBudget => Config.Budget is > 0;

    public double BudgetFractionValue => Config.Budget is { } b and > 0
        ? Math.Clamp(TotalCost / b, 0, 1.5)
        : 0;

    /// <summary>Resource key for the budget bar's fill color — green well
    /// under budget, yellow approaching it, red at/over, matching React's
    /// AgentsPage budget bar.</summary>
    public string BudgetBrushKey => BudgetFractionValue switch
    {
        >= 1.0 => "StatusErrorBrush",
        >= 0.8 => "StatusPausedBrush",
        _ => "StatusSuccessBrush"
    };

    private static string FormatRelative(DateTimeOffset at)
    {
        var delta = DateTimeOffset.UtcNow - at;
        if (delta.TotalMinutes < 1) return "just now";
        if (delta.TotalMinutes < 60) return $"{(int)delta.TotalMinutes}m ago";
        if (delta.TotalHours < 24) return $"{(int)delta.TotalHours}h ago";
        return $"{(int)delta.TotalDays}d ago";
    }

    private void Raise(string? name = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}

/// <summary>One row of <c>GET /v1/managed-agents/{id}/messages</c>. This is
/// a queue, not a live chat transcript — <c>Status</c> is "pending" until
/// the agent's next run processes it, then "delivered".</summary>
public sealed class AgentMessage
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("direction")]
    public string Direction { get; set; } = "";

    [JsonPropertyName("content")]
    public string Content { get; set; } = "";

    [JsonPropertyName("mode")]
    public string Mode { get; set; } = "queued";

    [JsonPropertyName("status")]
    public string Status { get; set; } = "pending";

    [JsonPropertyName("created_at")]
    public double CreatedAt { get; set; }

    public bool IsFromUser => Direction == "user_to_agent";
}

public sealed class AgentTask
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("description")]
    public string Description { get; set; } = "";

    [JsonPropertyName("status")]
    public string Status { get; set; } = "pending";
}

public sealed class AgentTemplate
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    [JsonPropertyName("description")]
    public string Description { get; set; } = "";

    [JsonPropertyName("icon")]
    public string Icon { get; set; } = "🤖";

    [JsonPropertyName("agent_type")]
    public string AgentType { get; set; } = "monitor_operative";

    [JsonPropertyName("schedule_type")]
    public string ScheduleType { get; set; } = "manual";

    [JsonPropertyName("schedule_value")]
    public string? ScheduleValue { get; set; }

    [JsonPropertyName("tools")]
    public List<string> Tools { get; set; } = [];

    [JsonPropertyName("max_turns")]
    public int MaxTurns { get; set; } = 10;

    [JsonPropertyName("temperature")]
    public double Temperature { get; set; } = 0.7;

    public string Label => $"{Icon} {Name}";
}

public sealed class ToolCatalogItem
{
    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    [JsonPropertyName("description")]
    public string Description { get; set; } = "";

    [JsonPropertyName("category")]
    public string Category { get; set; } = "";

    [JsonPropertyName("configured")]
    public bool Configured { get; set; }

    /// <summary>Checkbox binding target — toggled by the tool picker, not
    /// part of the backend payload.</summary>
    public bool IsSelected { get; set; }
}

/// <summary>Groups <see cref="ToolCatalogItem"/>s by category for the
/// create-agent wizard's tool picker — the backend returns a flat list,
/// grouping is client-side display structure only.</summary>
public sealed class ToolCatalogCategory
{
    public string Category { get; init; } = "";
    public List<ToolCatalogItem> Items { get; init; } = [];
}

public sealed class LearningLogEntry
{
    [JsonPropertyName("timestamp")]
    public double Timestamp { get; set; }

    [JsonPropertyName("summary")]
    public string Summary { get; set; } = "";
}
