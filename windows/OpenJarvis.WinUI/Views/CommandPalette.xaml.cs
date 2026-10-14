using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using OpenJarvis.WinUI.Models;

namespace OpenJarvis.WinUI.Views;

/// <summary>Ctrl+K quick switcher: pages, conversations, models, and
/// agents in one flat, substring-filtered list — not React's palette,
/// which is model-management only. Model pull/delete and cloud keys stay
/// on their existing pages/Settings.</summary>
public sealed partial class CommandPalette : UserControl
{
    private static readonly (string Tag, string Title)[] Pages =
    [
        ("chat", "Chat"),
        ("dashboard", "Dashboard"),
        ("datasources", "Data Sources"),
        ("agents", "Agents"),
        ("approvals", "Approvals"),
        ("logs", "Logs"),
        ("settings", "Settings"),
    ];

    private List<PaletteItem> _allItems = [];

    public event EventHandler<PaletteItem>? ItemActivated;
    public event EventHandler? CloseRequested;

    public CommandPalette()
    {
        InitializeComponent();
    }

    public async void Open()
    {
        Visibility = Visibility.Visible;
        FilterBox.Text = "";
        await LoadItemsAsync();
        ApplyFilter("");
        FilterBox.Focus(FocusState.Programmatic);
    }

    public void Close()
    {
        Visibility = Visibility.Collapsed;
        CloseRequested?.Invoke(this, EventArgs.Empty);
    }

    private async Task LoadItemsAsync()
    {
        var items = new List<PaletteItem>();

        items.AddRange(Pages.Select(p => new PaletteItem
        {
            Kind = PaletteItemKind.Page,
            Title = p.Title,
            Subtitle = "Page",
            Glyph = "",
            Payload = p.Tag
        }));

        items.AddRange(App.Services.Conversations.Items.Select(c => new PaletteItem
        {
            Kind = PaletteItemKind.Conversation,
            Title = c.Title,
            Subtitle = "Conversation",
            Glyph = "",
            Payload = c
        }));

        var catalog = await App.Services.Foundry.ListCatalogAsync(CancellationToken.None);
        var apiModels = await App.Services.Api.GetModelsAsync(CancellationToken.None);
        var modelIds = catalog.Installed.Count > 0 ? catalog.Installed : apiModels;
        items.AddRange(modelIds.Distinct(StringComparer.OrdinalIgnoreCase).Select(id => new PaletteItem
        {
            Kind = PaletteItemKind.Model,
            Title = id,
            Subtitle = "Model",
            Glyph = "",
            Payload = id
        }));

        var agents = await App.Services.Api.GetManagedAgentsAsync(CancellationToken.None);
        items.AddRange(agents.Select(a => new PaletteItem
        {
            Kind = PaletteItemKind.Agent,
            Title = a.Name,
            Subtitle = "Agent",
            Glyph = "",
            Payload = a.Id
        }));

        _allItems = items;
    }

    private void ApplyFilter(string query)
    {
        var trimmed = query.Trim();
        ResultsList.ItemsSource = trimmed.Length == 0
            ? _allItems
            : _allItems
                .Where(i => i.Title.Contains(trimmed, StringComparison.OrdinalIgnoreCase))
                .ToList();
    }

    private void FilterBox_TextChanged(object sender, TextChangedEventArgs e) => ApplyFilter(FilterBox.Text);

    private void FilterBox_KeyDown(object sender, KeyRoutedEventArgs e)
    {
        switch (e.Key)
        {
            case Windows.System.VirtualKey.Escape:
                e.Handled = true;
                Close();
                break;
            case Windows.System.VirtualKey.Down:
                e.Handled = true;
                ResultsList.Focus(FocusState.Programmatic);
                if (ResultsList.Items.Count > 0)
                {
                    ResultsList.SelectedIndex = 0;
                }

                break;
            case Windows.System.VirtualKey.Enter:
                e.Handled = true;
                if (ResultsList.Items.Count > 0)
                {
                    Activate((ResultsList.SelectedItem as PaletteItem) ?? (PaletteItem)ResultsList.Items[0]);
                }

                break;
        }
    }

    private void ResultsList_ItemClick(object sender, ItemClickEventArgs e)
    {
        if (e.ClickedItem is PaletteItem item)
        {
            Activate(item);
        }
    }

    private void Activate(PaletteItem item)
    {
        ItemActivated?.Invoke(this, item);
        Close();
    }

    private void Scrim_Tapped(object sender, Microsoft.UI.Xaml.Input.TappedRoutedEventArgs e) => Close();

    private void Panel_Tapped(object sender, Microsoft.UI.Xaml.Input.TappedRoutedEventArgs e) => e.Handled = true;
}
