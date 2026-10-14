using System.Collections.ObjectModel;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using OpenJarvis.WinUI.Models;

namespace OpenJarvis.WinUI.Views;

/// <summary>Renders the <c>POST /api/research</c> SSE timeline: an
/// "Analyzing query…" pulse before the first search, one row per search
/// step, a collapsible "N searches · N results" summary that auto-collapses
/// once synthesis starts, then a "Synthesizing findings…" pulse.</summary>
public sealed partial class ResearchTimelinePanel : UserControl
{
    private readonly ObservableCollection<ResearchStepItem> _steps = [];
    private bool _userToggledExpander;

    public ResearchTimelinePanel()
    {
        InitializeComponent();
        StepsList.ItemsSource = _steps;
        StepsExpander.Expanding += (_, _) => _userToggledExpander = true;
        StepsExpander.Collapsed += (_, _) => _userToggledExpander = true;
    }

    public void Reset()
    {
        _steps.Clear();
        _userToggledExpander = false;
        Root.Visibility = Visibility.Visible;
        AnalyzingRow.Visibility = Visibility.Visible;
        StepsExpander.Visibility = Visibility.Collapsed;
        StepsExpander.IsExpanded = false;
        SynthesizingRow.Visibility = Visibility.Collapsed;
        UpdateHeader();
    }

    public void Hide() => Root.Visibility = Visibility.Collapsed;

    public void AddSearchCall(string query)
    {
        AnalyzingRow.Visibility = Visibility.Collapsed;
        StepsExpander.Visibility = Visibility.Visible;
        _steps.Add(new ResearchStepItem { Query = query });
        UpdateHeader();
    }

    public void CompleteLatestSearch(int numHits, List<string> topTitles)
    {
        var step = _steps.LastOrDefault(s => !s.Complete);
        if (step is null)
        {
            return;
        }

        step.NumHits = numHits;
        step.TopTitlesLabel = topTitles.Count > 0 ? string.Join(" · ", topTitles.Take(2)) : "";
        step.Complete = true;
        UpdateHeader();
    }

    public void BeginSynthesizing()
    {
        AnalyzingRow.Visibility = Visibility.Collapsed;
        SynthesizingRow.Visibility = Visibility.Visible;
        if (!_userToggledExpander)
        {
            StepsExpander.IsExpanded = false;
        }
    }

    public void Finish() => SynthesizingRow.Visibility = Visibility.Collapsed;

    private void UpdateHeader()
    {
        var totalResults = _steps.Sum(s => s.NumHits);
        StepsHeaderText.Text = _steps.Count == 1
            ? $"1 search · {totalResults} results"
            : $"{_steps.Count} searches · {totalResults} results";
    }
}
