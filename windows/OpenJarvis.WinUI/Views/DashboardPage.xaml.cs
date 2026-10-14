using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using OpenJarvis.WinUI.Models;

namespace OpenJarvis.WinUI.Views;

public sealed partial class DashboardPage : Page
{
    private readonly DispatcherTimer _timer = new() { Interval = TimeSpan.FromSeconds(5) };
    private IReadOnlyList<TraceSummary> _traces = [];

    public DashboardPage()
    {
        InitializeComponent();
        Loaded += async (_, _) =>
        {
            await RefreshEnergyAsync();
            await RefreshCostAsync();
            await RefreshTracesAsync();
            _timer.Tick += async (_, _) => await RefreshEnergyAsync();
            _timer.Start();
        };
        Unloaded += (_, _) => _timer.Stop();
    }

    private async Task RefreshEnergyAsync()
    {
        var stats = await App.Services.Api.GetTelemetryStatsAsync(CancellationToken.None);
        var energy = await App.Services.Api.GetEnergyStatsAsync(CancellationToken.None);

        EnergyTiles.ItemsSource = new List<StatTile>
        {
            new() { Label = "Total energy", Value = FormatEnergy(energy?.TotalEnergyJ) },
            new() { Label = "Energy / token", Value = FormatSmallJoules(energy?.EnergyPerTokenJ) },
            new() { Label = "Avg power", Value = energy is null ? "—" : $"{energy.AvgPowerW:0.0} W" },
            new() { Label = "Thermal", Value = energy?.ThermalLabel ?? "—" },
            new() { Label = "Total requests", Value = stats is null ? "—" : stats.TotalRequests.ToString("N0") },
            new() { Label = "Tokens processed", Value = FormatTokens(stats?.TotalTokens) },
        };
    }

    private static string FormatEnergy(double? joules) =>
        joules is not { } j ? "—" : j >= 1000 ? $"{j / 1000:0.00} kJ" : $"{j:0} J";

    private static string FormatSmallJoules(double? joules) =>
        joules is not { } j ? "—" : $"{j:0.####} J";

    private static string FormatTokens(long? tokens)
    {
        if (tokens is not { } t)
        {
            return "—";
        }

        return t >= 1_000_000 ? $"{t / 1_000_000.0:0.#}M" : t >= 1_000 ? $"{t / 1_000.0:0.#}K" : t.ToString();
    }

    private async Task RefreshCostAsync()
    {
        var savings = await App.Services.Api.GetSavingsAsync(CancellationToken.None);
        LocalCostText.Text = savings is null ? "—" : $"${savings.LocalCost:0.0000}";
        ProviderCostList.ItemsSource = savings?.PerProvider ?? [];
    }

    private async Task RefreshTracesAsync()
    {
        _traces = await App.Services.Api.GetTracesAsync(50, CancellationToken.None);
        TraceList.ItemsSource = _traces;
        if (_traces.Count > 0)
        {
            TraceList.SelectedIndex = 0;
        }
    }

    private void TraceList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (TraceList.SelectedItem is not TraceSummary trace)
        {
            TraceStepList.ItemsSource = null;
            TraceEmptyText.Visibility = Visibility.Visible;
            return;
        }

        TraceEmptyText.Visibility = Visibility.Collapsed;
        TraceStepList.ItemsSource = trace.Steps;
    }
}
