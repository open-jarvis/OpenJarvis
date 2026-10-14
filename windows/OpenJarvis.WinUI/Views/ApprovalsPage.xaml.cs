using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using OpenJarvis.WinUI.Models;

namespace OpenJarvis.WinUI.Views;

public sealed partial class ApprovalsPage : Page
{
    private readonly DispatcherTimer _timer = new() { Interval = TimeSpan.FromSeconds(10) };

    public ApprovalsPage()
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
        var items = await App.Services.Api.GetPendingApprovalsAsync(CancellationToken.None);
        ApprovalList.ItemsSource = items;
    }

    private async void Approve_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button { Tag: string id })
        {
            await App.Services.Api.ApproveAsync(id, CancellationToken.None);
            await RefreshAsync();
        }
    }

    private async void Deny_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button { Tag: string id })
        {
            await App.Services.Api.DenyAsync(id, CancellationToken.None);
            await RefreshAsync();
        }
    }
}
