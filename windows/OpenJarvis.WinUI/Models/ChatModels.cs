using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Text.Json.Serialization;

namespace OpenJarvis.WinUI.Models;

public sealed class ToolCallInfo : INotifyPropertyChanged
{
    private string _status = "running";
    private string _arguments = "";
    private string? _result;
    private double? _latency;

    public event PropertyChangedEventHandler? PropertyChanged;

    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("tool")]
    public string Tool { get; set; } = "";

    [JsonPropertyName("arguments")]
    public string Arguments
    {
        get => _arguments;
        set
        {
            if (_arguments == value) return;
            _arguments = value;
            OnPropertyChanged();
        }
    }

    /// <summary>"running" while in flight, "success"/"error" once
    /// <c>tool_call_end</c> arrives. Bound with <c>Mode=OneWay</c> in the
    /// Expander-based tool-activity card so an already-rendered row's
    /// status glyph/latency actually update in place — the previous flat
    /// InfoBar template bound this with a default (OneTime) x:Bind, so a
    /// row never visually left "running" once drawn.</summary>
    [JsonPropertyName("status")]
    public string Status
    {
        get => _status;
        set
        {
            if (_status == value) return;
            _status = value;
            OnPropertyChanged();
            OnPropertyChanged(nameof(IsRunning));
            OnPropertyChanged(nameof(IsDone));
            OnPropertyChanged(nameof(StatusGlyph));
            OnPropertyChanged(nameof(StatusBrushKey));
        }
    }

    [JsonPropertyName("result")]
    public string? Result
    {
        get => _result;
        set
        {
            if (_result == value) return;
            _result = value;
            OnPropertyChanged();
        }
    }

    [JsonPropertyName("latency")]
    public double? Latency
    {
        get => _latency;
        set
        {
            if (_latency == value) return;
            _latency = value;
            OnPropertyChanged();
            OnPropertyChanged(nameof(LatencyLabel));
        }
    }

    public bool IsRunning => Status == "running";
    public bool IsDone => !IsRunning;

    public string StatusGlyph => Status switch
    {
        "success" => "", // CheckMark
        "error" => "", // Cancel
        _ => "" // Sync (running)
    };

    public string StatusBrushKey => Status switch
    {
        "success" => "StatusSuccessBrush",
        "error" => "StatusErrorBrush",
        _ => "StatusRunningBrush"
    };

    /// <summary><see cref="Latency"/> arrives from the backend in seconds
    /// (ToolExecutor's <c>latency_seconds</c>).</summary>
    public string LatencyLabel => Latency is { } seconds
        ? seconds >= 1 ? $"{seconds:0.0}s" : $"{seconds * 1000:0}ms"
        : "";

    public string ArgumentsPreview
    {
        get
        {
            if (string.IsNullOrWhiteSpace(Arguments))
            {
                return "";
            }

            var oneLine = Arguments.ReplaceLineEndings(" ");
            return oneLine.Length > 60 ? oneLine[..60] + "…" : oneLine;
        }
    }

    private void OnPropertyChanged([CallerMemberName] string? name = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}

public sealed class TokenUsage
{
    [JsonPropertyName("prompt_tokens")]
    public int PromptTokens { get; set; }

    [JsonPropertyName("completion_tokens")]
    public int CompletionTokens { get; set; }

    [JsonPropertyName("total_tokens")]
    public int TotalTokens { get; set; }
}

public sealed class ChatMessage : INotifyPropertyChanged
{
    private string _content = "";
    private bool _isPending;

    public event PropertyChangedEventHandler? PropertyChanged;

    [JsonPropertyName("id")]
    public string Id { get; set; } = Guid.NewGuid().ToString("N");

    [JsonPropertyName("role")]
    public string Role { get; set; } = "user";

    [JsonPropertyName("content")]
    public string Content
    {
        get => _content;
        set
        {
            if (_content == value)
            {
                return;
            }

            _content = value;
            OnPropertyChanged();
        }
    }

    /// <summary>True from send until the first content token (or the
    /// stream ending) — drives the "Thinking…" indicator.</summary>
    [JsonIgnore]
    public bool IsPending
    {
        get => _isPending;
        set
        {
            if (_isPending == value)
            {
                return;
            }

            _isPending = value;
            OnPropertyChanged();
        }
    }

    [JsonPropertyName("timestamp")]
    public long Timestamp { get; set; } = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

    [JsonPropertyName("toolCalls")]
    public List<ToolCallInfo> ToolCalls { get; set; } = [];

    private void OnPropertyChanged([CallerMemberName] string? name = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}

public sealed class Conversation : INotifyPropertyChanged
{
    private string _title = "New chat";

    public event PropertyChangedEventHandler? PropertyChanged;

    [JsonPropertyName("id")]
    public string Id { get; set; } = Guid.NewGuid().ToString("N");

    /// <summary>Display name only. Chats are stored and selected by <see cref="Id"/>.</summary>
    [JsonPropertyName("title")]
    public string Title
    {
        get => _title;
        set
        {
            if (_title == value)
            {
                return;
            }

            _title = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(Title)));
        }
    }

    [JsonPropertyName("createdAt")]
    public long CreatedAt { get; set; } = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

    [JsonPropertyName("updatedAt")]
    public long UpdatedAt { get; set; } = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

    [JsonPropertyName("model")]
    public string Model { get; set; } = "";

    [JsonPropertyName("messages")]
    public List<ChatMessage> Messages { get; set; } = [];
}

public sealed class ConversationStoreFile
{
    [JsonPropertyName("version")]
    public int Version { get; set; } = 1;

    [JsonPropertyName("conversations")]
    public Dictionary<string, Conversation> Conversations { get; set; } = [];

    [JsonPropertyName("activeId")]
    public string? ActiveId { get; set; }
}

public sealed class PendingApproval
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("tool")]
    public string Tool { get; set; } = "";

    [JsonPropertyName("summary")]
    public string Summary { get; set; } = "";

    [JsonPropertyName("tier")]
    public string Tier { get; set; } = "medium";

    [JsonPropertyName("created_at")]
    public string CreatedAt { get; set; } = "";
}

public sealed class ServerInfo
{
    [JsonPropertyName("model")]
    public string Model { get; set; } = "";

    [JsonPropertyName("agent")]
    public string Agent { get; set; } = "";

    [JsonPropertyName("engine")]
    public string Engine { get; set; } = "";

    [JsonPropertyName("allow_cloud")]
    public bool AllowCloud { get; set; }

    [JsonPropertyName("hardware")]
    public HardwareInfoDto? Hardware { get; set; }

    [JsonPropertyName("tool_calling")]
    public ToolCallingInfo? ToolCalling { get; set; }
}

public sealed class ToolCallingInfo
{
    [JsonPropertyName("supported")]
    public bool Supported { get; set; } = true;

    [JsonPropertyName("reason")]
    public string Reason { get; set; } = "";
}

public sealed class HardwareInfoDto
{
    [JsonPropertyName("platform")]
    public string Platform { get; set; } = "";

    [JsonPropertyName("arch")]
    public string Arch { get; set; } = "";

    [JsonPropertyName("cpu_brand")]
    public string CpuBrand { get; set; } = "";

    [JsonPropertyName("ram_gb")]
    public double RamGb { get; set; }

    [JsonPropertyName("execution_provider")]
    public string ExecutionProvider { get; set; } = "";

    [JsonPropertyName("execution_provider_fallback")]
    public bool ExecutionProviderFallback { get; set; }

    [JsonPropertyName("gpu")]
    public GpuInfoDto? Gpu { get; set; }
}

public sealed class GpuInfoDto
{
    [JsonPropertyName("vendor")]
    public string Vendor { get; set; } = "";

    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    [JsonPropertyName("vram_gb")]
    public double VramGb { get; set; }
}

public sealed class ModelItem
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";
}

public sealed class FoundryModelCatalog
{
    public IReadOnlyList<string> Installed { get; init; } = [];
    public IReadOnlyList<string> Available { get; init; } = [];
}

public sealed class AppSettings
{
    public string ApiUrl { get; set; } = "http://127.0.0.1:8000";
    public string Theme { get; set; } = "Default";
    public double Temperature { get; set; } = 0.7;
    public int MaxTokens { get; set; } = 1024;
    public string SelectedModel { get; set; } = "Phi-4-mini-instruct";
    public double NavPaneWidth { get; set; }
    public bool AllowCloud { get; set; }
    public bool LocalSetupConsented { get; set; }
    public bool MemoryContextEnabled { get; set; } = true;
    public string MemoryBackend { get; set; } = "sqlite";
    public int MemoryTopK { get; set; } = 5;
    public double MemoryMinScore { get; set; } = 0.1;
    public int MemoryMaxTokens { get; set; } = 2048;
    public bool VoiceOutputEnabled { get; set; }
    public bool VoiceAutoplay { get; set; }
}

public enum SetupStep
{
    Engine,
    Model,
    Server,
    Done
}

public sealed class BackendStatus
{
    public string Phase { get; set; } = "Starting";
    public string Detail { get; set; } = "";
    public SetupStep Step { get; set; } = SetupStep.Engine;
    public bool Ready { get; set; }
    public bool Failed { get; set; }
}

public sealed class ChatDisplayItem
{
    public ChatMessage Message { get; init; } = new();
    public ObservableCollection<ToolCallInfo> ToolCalls { get; } = [];
}
