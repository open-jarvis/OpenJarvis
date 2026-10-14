using System.ComponentModel;
using System.Text.Json.Serialization;

namespace OpenJarvis.WinUI.Models;

/// <summary>One source citation as emitted by <c>POST /api/research</c>'s
/// <c>search_result</c>/<c>final_sources</c>/<c>done</c> frames.</summary>
public sealed class ResearchSource
{
    [JsonPropertyName("ref")]
    public int Ref { get; set; }

    [JsonPropertyName("title")]
    public string? Title { get; set; }

    [JsonPropertyName("sender")]
    public string? Sender { get; set; }

    [JsonPropertyName("date")]
    public string? Date { get; set; }

    [JsonPropertyName("source_id")]
    public string? SourceId { get; set; }

    [JsonPropertyName("url")]
    public string? Url { get; set; }
}

/// <summary><c>search_call</c> frame.</summary>
public sealed class ResearchSearchCall
{
    [JsonPropertyName("arguments")]
    public Dictionary<string, object?>? Arguments { get; set; }

    public string? Query =>
        Arguments is not null && Arguments.TryGetValue("query", out var value)
            ? value?.ToString()
            : null;
}

/// <summary><c>search_result</c> frame.</summary>
public sealed class ResearchSearchResult
{
    [JsonPropertyName("num_hits")]
    public int NumHits { get; set; }

    [JsonPropertyName("top_titles")]
    public List<string> TopTitles { get; set; } = [];

    [JsonPropertyName("sources")]
    public List<ResearchSource> Sources { get; set; } = [];
}

/// <summary><c>synthesis</c> frame — one chunk of the final answer.</summary>
public sealed class ResearchSynthesisChunk
{
    [JsonPropertyName("text")]
    public string Text { get; set; } = "";
}

/// <summary><c>final_sources</c> frame.</summary>
public sealed class ResearchFinalSources
{
    [JsonPropertyName("sources")]
    public List<ResearchSource> Sources { get; set; } = [];
}

/// <summary><c>done</c> frame — always the terminal frame of the stream.</summary>
public sealed class ResearchDone
{
    [JsonPropertyName("usage")]
    public Dictionary<string, object?>? Usage { get; set; }

    [JsonPropertyName("sources")]
    public List<ResearchSource> Sources { get; set; } = [];
}

/// <summary><c>error</c> frame.</summary>
public sealed class ResearchError
{
    [JsonPropertyName("message")]
    public string Message { get; set; } = "";
}

/// <summary>One timeline row the UI renders per search step, built up as
/// <c>search_call</c>/<c>search_result</c> frames arrive for the same step.</summary>
public sealed class ResearchStepItem : INotifyPropertyChanged
{
    private bool _complete;
    private int _numHits;
    private string _topTitlesLabel = "";

    public event PropertyChangedEventHandler? PropertyChanged;

    public string Query { get; init; } = "";

    public bool Complete
    {
        get => _complete;
        set
        {
            if (_complete == value) return;
            _complete = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(Complete)));
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(CompleteInverse)));
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(ResultsLabel)));
        }
    }

    public bool CompleteInverse => !Complete;

    public int NumHits
    {
        get => _numHits;
        set
        {
            if (_numHits == value) return;
            _numHits = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(NumHits)));
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(ResultsLabel)));
        }
    }

    public string TopTitlesLabel
    {
        get => _topTitlesLabel;
        set
        {
            if (_topTitlesLabel == value) return;
            _topTitlesLabel = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(TopTitlesLabel)));
        }
    }

    public string ResultsLabel => NumHits == 1 ? "1 result" : $"{NumHits} results";
}
