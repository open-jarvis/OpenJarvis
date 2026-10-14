using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using OpenJarvis.WinUI.Models;

namespace OpenJarvis.WinUI.Views;

/// <summary>
/// Conversation list shown in the navigation pane on every page, the WinUI
/// counterpart of the React client's sidebar <c>ConversationList</c>.
/// </summary>
public sealed partial class ChatListPane : UserControl
{
    private bool _deletePressed;
    private bool _suppressListSelection;

    /// <summary>Raised when the user opens or starts a chat from the pane.</summary>
    public event EventHandler? ConversationOpened;

    public ChatListPane()
    {
        InitializeComponent();
        App.Services.Conversations.Items.CollectionChanged += (_, _) => ApplyConversationFilter();
        App.Services.Conversations.ActiveChanged += (_, _) => SyncSelection();
        ApplyConversationFilter();
    }

    private void ConversationSearchBox_TextChanged(
        AutoSuggestBox sender, AutoSuggestBoxTextChangedEventArgs args) =>
        ApplyConversationFilter();

    private void ApplyConversationFilter()
    {
        var query = ConversationSearchBox?.Text?.Trim() ?? "";
        var items = App.Services.Conversations.Items.AsEnumerable();
        if (query.Length > 0)
        {
            items = items.Where(c => c.Title.Contains(query, StringComparison.OrdinalIgnoreCase));
        }

        _suppressListSelection = true;
        try
        {
            ConversationList.ItemsSource = items.ToList();
            ConversationList.SelectedItem = App.Services.Conversations.Active;
        }
        finally
        {
            _suppressListSelection = false;
        }
    }

    private void SyncSelection()
    {
        _suppressListSelection = true;
        try
        {
            ConversationList.SelectedItem = App.Services.Conversations.Active;
        }
        finally
        {
            _suppressListSelection = false;
        }
    }

    private void NewChat_Click(object sender, RoutedEventArgs e)
    {
        App.Services.Conversations.NewConversation(App.Services.Settings.Current.SelectedModel);
        ConversationOpened?.Invoke(this, EventArgs.Empty);
    }

    private void ConversationList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_suppressListSelection)
        {
            return;
        }

        if (_deletePressed)
        {
            _deletePressed = false;
            SyncSelection();
            return;
        }

        if (ConversationList.SelectedItem is Conversation conversation)
        {
            App.Services.Conversations.Select(conversation);
            ConversationOpened?.Invoke(this, EventArgs.Empty);
        }
    }

    private void ConversationList_ContainerContentChanging(
        ListViewBase sender, ContainerContentChangingEventArgs args)
    {
        if (args.ItemContainer is not ListViewItem container)
        {
            return;
        }

        if (args.InRecycleQueue || args.Item is not Conversation conversation)
        {
            container.ContextFlyout = null;
            return;
        }

        var rename = new MenuFlyoutItem
        {
            Text = "Rename",
            Tag = conversation.Id,
            Icon = new SymbolIcon(Symbol.Rename)
        };
        rename.Click += RenameChat_Click;
        var delete = new MenuFlyoutItem
        {
            Text = "Delete",
            Tag = conversation.Id,
            Icon = new SymbolIcon(Symbol.Delete)
        };
        delete.Click += DeleteChat_Click;

        var menu = new MenuFlyout();
        menu.Items.Add(rename);
        menu.Items.Add(delete);
        container.ContextFlyout = menu;
    }

    private void DeleteChat_PointerPressed(object sender, PointerRoutedEventArgs e)
    {
        _deletePressed = true;
    }

    private async void RenameChat_Click(object sender, RoutedEventArgs e)
    {
        var conversation = FindConversation(sender);
        if (conversation is null)
        {
            return;
        }

        var box = new TextBox
        {
            Text = conversation.Title,
            PlaceholderText = "Chat name",
            MinWidth = 280
        };
        var dialog = new ContentDialog
        {
            Title = "Rename chat",
            Content = box,
            PrimaryButtonText = "Rename",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Primary,
            XamlRoot = XamlRoot,
            RequestedTheme = App.Services.Settings.CurrentElementTheme()
        };
        dialog.Opened += (_, _) =>
        {
            box.SelectAll();
            box.Focus(FocusState.Programmatic);
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary)
        {
            return;
        }

        App.Services.Conversations.Rename(conversation, box.Text);
        if (!string.IsNullOrWhiteSpace(ConversationSearchBox.Text))
        {
            ApplyConversationFilter();
        }
    }

    private async void DeleteChat_Click(object sender, RoutedEventArgs e)
    {
        _deletePressed = false;
        var conversation = FindConversation(sender);
        if (conversation is null)
        {
            return;
        }

        var conversations = App.Services.Conversations;

        var dialog = new ContentDialog
        {
            Title = "Delete chat?",
            Content = $"\"{conversation.Title}\" will be removed from this device.",
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

        conversations.Delete(conversation);
        if (conversations.Active is null)
        {
            conversations.NewConversation(App.Services.Settings.Current.SelectedModel);
        }
    }

    private static Conversation? FindConversation(object sender)
    {
        if (sender is not FrameworkElement { Tag: string id })
        {
            return null;
        }

        return App.Services.Conversations.Items.FirstOrDefault(c => c.Id == id);
    }
}
