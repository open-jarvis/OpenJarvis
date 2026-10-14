using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;
using OpenJarvis.WinUI.Models;

namespace OpenJarvis.WinUI.Views;

public sealed partial class AgentDetailPage : Page
{
    private readonly DispatcherTimer _timer = new() { Interval = TimeSpan.FromSeconds(5) };
    private string _agentId = "";

    public AgentDetailPage()
    {
        InitializeComponent();
        Unloaded += (_, _) => _timer.Stop();
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        if (e.Parameter is not string agentId)
        {
            return;
        }

        _agentId = agentId;
        MessagingTab.AgentId = agentId;
        _ = RefreshAllAsync();
        _timer.Tick += async (_, _) => await RefreshAllAsync();
        _timer.Start();
    }

    private async Task RefreshAllAsync()
    {
        var agent = await App.Services.Api.GetManagedAgentAsync(_agentId, CancellationToken.None);
        if (agent is not null)
        {
            ApplyOverview(agent);
        }

        var messages = await App.Services.Api.GetAgentMessagesAsync(_agentId, CancellationToken.None);
        InteractList.ItemsSource = messages.OrderBy(m => m.CreatedAt).ToList();

        var tasks = await App.Services.Api.GetAgentTasksAsync(_agentId, CancellationToken.None);
        TaskList.ItemsSource = tasks;

        var learning = await App.Services.Api.GetLearningLogAsync(_agentId, CancellationToken.None);
        LearningList.ItemsSource = learning;
    }

    private void ApplyOverview(ManagedAgentSummary agent)
    {
        AgentNameText.Text = agent.Name;
        OverviewText.Text =
            $"{agent.AgentType}\n" +
            $"Status: {agent.Status}\n" +
            $"Schedule: {agent.Config.ScheduleLabel}\n" +
            $"Runs: {agent.TotalRuns}  ·  Cost: {agent.CostLabel}  ·  Last run: {agent.LastRunLabel}";
        MemoryText.Text = string.IsNullOrWhiteSpace(agent.SummaryMemory)
            ? "No memory recorded yet."
            : agent.SummaryMemory;

        BudgetBar.Visibility = agent.HasBudget ? Visibility.Visible : Visibility.Collapsed;
        BudgetBar.Value = agent.BudgetFractionValue;

        RunButton.IsEnabled = agent.CanRun;
        PauseButton.IsEnabled = agent.CanPause;
        ResumeButton.IsEnabled = agent.CanResume;
        RecoverButton.IsEnabled = agent.CanRecover;
    }

    private void Back_Click(object sender, RoutedEventArgs e)
    {
        if (Frame?.CanGoBack == true)
        {
            Frame.GoBack();
        }
    }

    private async void Run_Click(object sender, RoutedEventArgs e)
    {
        await App.Services.Api.RunAgentAsync(_agentId, CancellationToken.None);
        await RefreshAllAsync();
    }

    private async void Pause_Click(object sender, RoutedEventArgs e)
    {
        await App.Services.Api.PauseAgentAsync(_agentId, CancellationToken.None);
        await RefreshAllAsync();
    }

    private async void Resume_Click(object sender, RoutedEventArgs e)
    {
        await App.Services.Api.ResumeAgentAsync(_agentId, CancellationToken.None);
        await RefreshAllAsync();
    }

    private async void Recover_Click(object sender, RoutedEventArgs e)
    {
        await App.Services.Api.RecoverAgentAsync(_agentId, CancellationToken.None);
        await RefreshAllAsync();
    }

    private async void SendInteract_Click(object sender, RoutedEventArgs e)
    {
        var text = InteractBox.Text.Trim();
        if (text.Length == 0)
        {
            return;
        }

        InteractBox.Text = "";
        await App.Services.Api.PostAgentMessageAsync(_agentId, text, "immediate", CancellationToken.None);
        await RefreshAllAsync();
    }

    private async void AddTask_Click(object sender, RoutedEventArgs e)
    {
        var text = NewTaskBox.Text.Trim();
        if (text.Length == 0)
        {
            return;
        }

        NewTaskBox.Text = "";
        await App.Services.Api.CreateAgentTaskAsync(_agentId, text, CancellationToken.None);
        await RefreshAllAsync();
    }

    private async void RunLearning_Click(object sender, RoutedEventArgs e)
    {
        await App.Services.Api.RunLearningAsync(_agentId, CancellationToken.None);
        await RefreshAllAsync();
    }
}
