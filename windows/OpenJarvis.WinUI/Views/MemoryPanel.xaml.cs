using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Windows.Storage.Pickers;

namespace OpenJarvis.WinUI.Views;

/// <summary>Memory store/search/index — the WinUI counterpart of React's
/// Data Sources "Memory" tab. There is no backend endpoint to enumerate or
/// delete individual entries (only semantic search), so this is not a full
/// browser — store, search, and index only.</summary>
public sealed partial class MemoryPanel : UserControl
{
    private readonly DispatcherTimer _statsTimer = new() { Interval = TimeSpan.FromSeconds(10) };

    public MemoryPanel()
    {
        InitializeComponent();
        Loaded += async (_, _) =>
        {
            await RefreshStatsAsync();
            _statsTimer.Tick += async (_, _) => await RefreshStatsAsync();
            _statsTimer.Start();
        };
        Unloaded += (_, _) => _statsTimer.Stop();
    }

    private async Task RefreshStatsAsync()
    {
        var stats = await App.Services.Api.GetMemoryStatsAsync(CancellationToken.None);
        if (stats is null || stats.Status == "not_configured")
        {
            StatsIcon.Glyph = ""; // Info
            StatsText.Text = "Memory is not configured.";
            return;
        }

        StatsIcon.Glyph = stats.Entries > 0 ? "" : ""; // CheckMark / Sync
        StatsText.Text = $"{stats.Backend} · {stats.Entries} entries";
    }

    private async void SearchBox_KeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key == Windows.System.VirtualKey.Enter)
        {
            e.Handled = true;
            await RunSearchAsync();
        }
    }

    private async void Search_Click(object sender, RoutedEventArgs e) => await RunSearchAsync();

    private async Task RunSearchAsync()
    {
        var query = SearchBox.Text.Trim();
        if (query.Length == 0)
        {
            return;
        }

        var results = await App.Services.Api.SearchMemoryAsync(query, 10, CancellationToken.None);
        SearchResultsList.ItemsSource = results;
        SearchEmptyText.Visibility = results.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
    }

    private async void Browse_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FolderPicker();
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowInstance);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var folder = await picker.PickSingleFolderAsync();
        if (folder is not null)
        {
            IndexPathBox.Text = folder.Path;
        }
    }

    private async void Index_Click(object sender, RoutedEventArgs e)
    {
        var path = IndexPathBox.Text.Trim();
        if (path.Length == 0)
        {
            return;
        }

        IndexResultText.Text = "Indexing…";
        var result = await App.Services.Api.IndexMemoryPathAsync(path, CancellationToken.None);
        IndexResultText.Text = result switch
        {
            null => "Could not index that path.",
            { Note: { Length: > 0 } note } => note,
            _ => $"Indexed {result.ChunksIndexed} chunks."
        };
        await RefreshStatsAsync();
    }

    private async void Store_Click(object sender, RoutedEventArgs e)
    {
        var text = StoreTextBox.Text.Trim();
        if (text.Length == 0)
        {
            return;
        }

        var ok = await App.Services.Api.StoreMemoryAsync(text, null, CancellationToken.None);
        StoreResultText.Text = ok ? "Stored successfully." : "Could not store that text.";
        if (ok)
        {
            StoreTextBox.Text = "";
        }

        await RefreshStatsAsync();
    }
}
