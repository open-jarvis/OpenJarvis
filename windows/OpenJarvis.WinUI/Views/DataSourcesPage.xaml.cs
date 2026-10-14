using System.Diagnostics;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using OpenJarvis.WinUI.Models;
using OpenJarvis.WinUI.Services;

namespace OpenJarvis.WinUI.Views;

public sealed partial class DataSourcesPage : Page
{
    private readonly DispatcherTimer _listTimer = new() { Interval = TimeSpan.FromSeconds(10) };
    private readonly DispatcherTimer _syncTimer = new() { Interval = TimeSpan.FromSeconds(5) };
    private DispatcherTimer? _oauthPollTimer;

    public DataSourcesPage()
    {
        InitializeComponent();
        Loaded += async (_, _) =>
        {
            await RefreshListsAsync();
            _listTimer.Tick += async (_, _) => await RefreshListsAsync();
            _listTimer.Start();
            _syncTimer.Tick += async (_, _) => await PollActiveSyncsAsync();
            _syncTimer.Start();
        };
        Unloaded += (_, _) =>
        {
            _listTimer.Stop();
            _syncTimer.Stop();
            _oauthPollTimer?.Stop();
        };
    }

    private async Task RefreshListsAsync()
    {
        var connectors = await App.Services.Api.GetConnectorsAsync(CancellationToken.None);
        var connected = connectors.Where(c => c.Connected).ToList();
        var available = connectors.Where(c => !c.Connected).ToList();

        ConnectedList.ItemsSource = connected;
        AvailableList.ItemsSource = available;
        ConnectedHeader.Text = $"Connected · {connected.Count}";
        AvailableHeader.Text = $"Available · {available.Count}";

        foreach (var c in connected)
        {
            _ = RefreshSyncStatusAsync(c.ConnectorId);
        }
    }

    private async Task PollActiveSyncsAsync()
    {
        if (ConnectedList.ItemsSource is not IEnumerable<ConnectorSummary> connected)
        {
            return;
        }

        foreach (var c in connected)
        {
            await RefreshSyncStatusAsync(c.ConnectorId);
        }
    }

    private async Task RefreshSyncStatusAsync(string connectorId)
    {
        var status = await App.Services.Api.GetSyncStatusAsync(connectorId, CancellationToken.None);
        var item = (ConnectedList.ItemsSource as IEnumerable<ConnectorSummary>)?
            .FirstOrDefault(c => c.ConnectorId == connectorId);
        if (status is not null && item is not null)
        {
            item.SyncStatusLabel = status.StatusLabel;
        }
    }

    private async void Sync_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not FrameworkElement { Tag: ConnectorSummary c })
        {
            return;
        }

        await App.Services.Api.StartSyncAsync(c.ConnectorId, CancellationToken.None);
        await RefreshSyncStatusAsync(c.ConnectorId);
    }

    private async void Disconnect_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not FrameworkElement { Tag: ConnectorSummary c })
        {
            return;
        }

        // The backend serializes connector lifecycle ops behind a lock and
        // 409s with "still stopping" during a disconnect race — retry a
        // few times rather than treating that as a hard failure.
        for (var attempt = 0; attempt < 3; attempt++)
        {
            var result = await App.Services.Api.DisconnectConnectorAsync(c.ConnectorId, CancellationToken.None);
            if (result is not null)
            {
                break;
            }

            await Task.Delay(1000);
        }

        await RefreshListsAsync();
    }

    private async void ConnectLocal_Click(object sender, RoutedEventArgs e) =>
        await ConnectAsync(sender, new { });

    private async void ConnectFilesystem_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not FrameworkElement { Tag: ConnectorSummary } button)
        {
            return;
        }

        var pathBox = button.FindName("PathBox") as TextBox;
        await ConnectAsync(sender, new { path = pathBox?.Text ?? "" });
    }

    private async void ConnectToken_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not FrameworkElement { Tag: ConnectorSummary } button)
        {
            return;
        }

        var tokenBox = button.FindName("TokenBox") as PasswordBox;
        await ConnectAsync(sender, new { token = tokenBox?.Password ?? "" });
    }

    private async Task ConnectAsync(object sender, object body)
    {
        if (sender is not FrameworkElement { Tag: ConnectorSummary c })
        {
            return;
        }

        var result = await App.Services.Api.ConnectConnectorAsync(c.ConnectorId, body, CancellationToken.None);
        if (result is null)
        {
            App.Services.Logs.Append("connectors", "error", $"Could not connect {c.DisplayName}.");
        }

        await RefreshListsAsync();
    }

    private void ConnectOAuth_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not FrameworkElement { Tag: ConnectorSummary c } button)
        {
            return;
        }

        _ = StartOAuthAsync(c, button);
    }

    private async Task StartOAuthAsync(ConnectorSummary c, FrameworkElement formRoot)
    {
        var detail = await App.Services.Api.GetConnectorDetailAsync(c.ConnectorId, CancellationToken.None);
        if (detail?.AuthUrl is not { Length: > 0 } url)
        {
            App.Services.Logs.Append("connectors", "error", $"{c.DisplayName} has no OAuth URL configured.");
            return;
        }

        Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });

        var waitingText = formRoot.FindName("OAuthWaitingText") as TextBlock;
        if (waitingText is not null)
        {
            waitingText.Text = "Waiting for sign-in in your browser…";
            waitingText.Visibility = Visibility.Visible;
        }

        _oauthPollTimer?.Stop();
        _oauthPollTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(2) };
        var attempts = 0;
        _oauthPollTimer.Tick += async (_, _) =>
        {
            attempts++;
            var current = await App.Services.Api.GetConnectorDetailAsync(c.ConnectorId, CancellationToken.None);
            if (current?.Connected == true || attempts > 150) // ~5 minutes
            {
                _oauthPollTimer?.Stop();
                if (waitingText is not null)
                {
                    waitingText.Visibility = Visibility.Collapsed;
                }

                await RefreshListsAsync();
            }
        };
        _oauthPollTimer.Start();
    }
}
