using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using OpenJarvis.WinUI.Models;

namespace OpenJarvis.WinUI.Views;

public sealed partial class AgentsPage : Page
{
    private readonly DispatcherTimer _timer = new() { Interval = TimeSpan.FromSeconds(5) };

    public AgentsPage()
    {
        InitializeComponent();
        Loaded += async (_, _) =>
        {
            await RefreshAsync();
            _timer.Tick += async (_, _) => await RefreshAsync();
            _timer.Start();
        };
        Unloaded += (_, _) => _timer.Stop();
    }

    private async Task RefreshAsync()
    {
        var agents = await App.Services.Api.GetManagedAgentsAsync(CancellationToken.None);
        var existing = (AgentList.ItemsSource as IEnumerable<ManagedAgentSummary>)?
            .ToDictionary(a => a.Id) ?? new Dictionary<string, ManagedAgentSummary>();

        // Update in place when we already have this row so status/cost
        // changes animate via its own INotifyPropertyChanged rather than
        // resetting the whole ListView (and losing scroll position).
        foreach (var fresh in agents)
        {
            if (existing.TryGetValue(fresh.Id, out var current))
            {
                current.Status = fresh.Status;
                current.TotalCost = fresh.TotalCost;
                current.TotalRuns = fresh.TotalRuns;
                current.CurrentActivity = fresh.CurrentActivity;
                current.LastRunAt = fresh.LastRunAt;
            }
        }

        if (AgentList.ItemsSource is null || existing.Count != agents.Count)
        {
            AgentList.ItemsSource = agents;
        }
    }

    private async void NewAgent_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new CreateAgentDialog
        {
            XamlRoot = XamlRoot,
            RequestedTheme = App.Services.Settings.CurrentElementTheme()
        };
        if (await dialog.ShowAsync() == ContentDialogResult.Primary && dialog.Result is { } body)
        {
            await App.Services.Api.CreateManagedAgentAsync(body, CancellationToken.None);
            await RefreshAsync();
        }
    }

    private void Chat_Click(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { Tag: ManagedAgentSummary agent } &&
            Frame is not null)
        {
            Frame.Navigate(typeof(AgentDetailPage), agent.Id);
        }
    }

    private async void Run_Click(object sender, RoutedEventArgs e) =>
        await LifecycleAsync(sender, App.Services.Api.RunAgentAsync);

    private async void Pause_Click(object sender, RoutedEventArgs e) =>
        await LifecycleAsync(sender, App.Services.Api.PauseAgentAsync);

    private async void Resume_Click(object sender, RoutedEventArgs e) =>
        await LifecycleAsync(sender, App.Services.Api.ResumeAgentAsync);

    private async void Recover_Click(object sender, RoutedEventArgs e) =>
        await LifecycleAsync(sender, App.Services.Api.RecoverAgentAsync);

    private async Task LifecycleAsync(
        object sender, Func<string, CancellationToken, Task<string?>> action)
    {
        if (sender is not FrameworkElement { Tag: ManagedAgentSummary agent })
        {
            return;
        }

        var status = await action(agent.Id, CancellationToken.None);
        if (status is not null && status != "already_running")
        {
            agent.Status = status;
        }

        await RefreshAsync();
    }

    private async void Delete_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not FrameworkElement { Tag: ManagedAgentSummary agent })
        {
            return;
        }

        var dialog = new ContentDialog
        {
            Title = "Delete agent?",
            Content = $"\"{agent.Name}\" will be archived and removed from this list.",
            PrimaryButtonText = "Delete",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close,
            XamlRoot = XamlRoot,
            RequestedTheme = App.Services.Settings.CurrentElementTheme()
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary)
        {
            return;
        }

        await App.Services.Api.DeleteManagedAgentAsync(agent.Id, CancellationToken.None);
        await RefreshAsync();
    }
}
