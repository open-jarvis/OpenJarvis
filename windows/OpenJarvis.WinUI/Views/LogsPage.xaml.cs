using System.Collections.Specialized;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace OpenJarvis.WinUI.Views;

public sealed partial class LogsPage : Page
{
    public LogsPage()
    {
        InitializeComponent();
        LogList.ItemsSource = App.Services.Logs.Entries;
        UpdateCount();
        Loaded += (_, _) => App.Services.Logs.Entries.CollectionChanged += OnEntriesChanged;
        Unloaded += (_, _) => App.Services.Logs.Entries.CollectionChanged -= OnEntriesChanged;
    }

    private void OnEntriesChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        UpdateCount();
        if (LogList.Items.Count > 0)
        {
            LogList.ScrollIntoView(LogList.Items[^1]);
        }
    }

    private void UpdateCount() => CountText.Text = $"({App.Services.Logs.Entries.Count})";

    private void CopyAll_Click(object sender, RoutedEventArgs e)
    {
        var package = new Windows.ApplicationModel.DataTransfer.DataPackage();
        package.SetText(App.Services.Logs.CopyAllAsText());
        Windows.ApplicationModel.DataTransfer.Clipboard.SetContent(package);
    }

    private void Clear_Click(object sender, RoutedEventArgs e) => App.Services.Logs.Clear();
}
