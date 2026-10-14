using System.Collections.ObjectModel;
using System.Text.Json;
using Microsoft.UI.Input;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using OpenJarvis.WinUI.Models;
using OpenJarvis.WinUI.Services;

namespace OpenJarvis.WinUI.Views;

public sealed partial class ChatPage : Page
{
    private readonly ObservableCollection<ChatMessage> _messages = [];
    private readonly ObservableCollection<ToolCallInfo> _tools = [];
    private CancellationTokenSource? _sendCts;
    private bool _sending;

    private Conversation? _active;
    private bool _suppressModelChange;

    public ChatPage()
    {
        InitializeComponent();
        MessageList.ItemsSource = _messages;
        ToolList.ItemsSource = _tools;
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
        App.Services.Supervisor.StatusChanged += OnBackendStatusChanged;
        App.Services.Conversations.ActiveChanged += OnActiveConversationChanged;
    }

    private void OnUnloaded(object sender, RoutedEventArgs e)
    {
        App.Services.Supervisor.StatusChanged -= OnBackendStatusChanged;
        App.Services.Conversations.ActiveChanged -= OnActiveConversationChanged;
    }

    private void OnActiveConversationChanged(object? sender, EventArgs e)
    {
        if (_active is not null && !App.Services.Conversations.Items.Contains(_active))
        {
            _sendCts?.Cancel();
        }

        _active = App.Services.Conversations.Active;
        ReloadMessages();
        _tools.Clear();
    }

    private void ToggleTheme_Click(object sender, RoutedEventArgs e)
    {
        var next = App.Services.Settings.CycleTheme();
        ThemeToggleIcon.Glyph = next switch
        {
            "Light" => "", // Sunny
            "Dark" => "", // ClearNight
            _ => "" // Settings/auto-ish glyph for "system"
        };
    }

    private void OnBackendStatusChanged(object? sender, EventArgs e)
    {
        DispatcherQueue.TryEnqueue(() =>
        {
            SyncSelectedModel();
            SyncSendButton();
        });
    }

    private void SyncSendButton()
    {
        SendButton.Visibility = _sending ? Visibility.Collapsed : Visibility.Visible;
        CancelButton.Visibility = _sending ? Visibility.Visible : Visibility.Collapsed;
        SendButton.IsEnabled = !_sending && App.Services.Supervisor.Status.Ready;
    }

    private void SyncSelectedModel()
    {
        var model = App.Services.Settings.Current.SelectedModel;
        if (string.IsNullOrWhiteSpace(model) || SelectedModelId() == model)
        {
            return;
        }

        _suppressModelChange = true;
        try
        {
            EnsureModelInPicker(model, installed: true);
            SelectModelInPicker(model);
            if (_active is not null)
            {
                _active.Model = model;
            }
        }
        finally
        {
            _suppressModelChange = false;
        }
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        _active = App.Services.Conversations.Active;
        if (_active is null)
        {
            _active = App.Services.Conversations.NewConversation(App.Services.Settings.Current.SelectedModel);
        }

        ReloadMessages();
        SyncSendButton();
        MicButton.Visibility = SpeechService.IsRecognitionAvailable() ? Visibility.Visible : Visibility.Collapsed;
        await RefreshServerAsync();
    }

    private void ReloadMessages()
    {
        _messages.Clear();
        if (_active is null)
        {
            return;
        }

        foreach (var message in _active.Messages)
        {
            _messages.Add(message);
        }

        ScrollToLatest();
    }

    /// <summary>Deferred so the list has realized containers: messages are
    /// variable-height Markdown, so jumping straight to the estimated
    /// <c>ScrollableHeight</c> before the last item is measured undershoots.</summary>
    private void ScrollToLatest()
    {
        if (_messages.Count == 0)
        {
            return;
        }

        var last = _messages[^1];
        DispatcherQueue.TryEnqueue(Microsoft.UI.Dispatching.DispatcherQueuePriority.Low, () =>
        {
            if (_messages.Count == 0 || !ReferenceEquals(_messages[^1], last))
            {
                return;
            }

            MessageList.ScrollIntoView(last, ScrollIntoViewAlignment.Leading);
            MessageList.UpdateLayout();
            if (FindDescendant<ScrollViewer>(MessageList) is { } viewer)
            {
                viewer.ChangeView(null, viewer.ScrollableHeight, null, disableAnimation: true);
            }
        });
    }

    private static T? FindDescendant<T>(DependencyObject root) where T : DependencyObject
    {
        for (var i = 0; i < VisualTreeHelper.GetChildrenCount(root); i++)
        {
            var child = VisualTreeHelper.GetChild(root, i);
            if (child is T match)
            {
                return match;
            }

            if (FindDescendant<T>(child) is { } nested)
            {
                return nested;
            }
        }

        return null;
    }

    private async Task RefreshServerAsync()
    {
        var catalog = await App.Services.Foundry.ListCatalogAsync(CancellationToken.None);
        var apiModels = await App.Services.Api.GetModelsAsync(CancellationToken.None);
        _suppressModelChange = true;
        try
        {
            PopulateModelPicker(catalog, apiModels);
            var selected = App.Services.Settings.Current.SelectedModel;
            if (!SelectModelInPicker(selected) && ModelBox.Items.Count > 0)
            {
                ModelBox.SelectedIndex = FirstSelectableIndex();
            }
        }
        finally
        {
            _suppressModelChange = false;
        }
    }

    private const string AvailableSeparator = "── Available to download ──";

    private void PopulateModelPicker(FoundryModelCatalog catalog, IReadOnlyList<string> apiModels)
    {
        ModelBox.ItemsSource = null;
        ModelBox.Items.Clear();

        var installed = catalog.Installed.Count > 0
            ? catalog.Installed
            : apiModels;
        var selected = App.Services.Settings.Current.SelectedModel;
        if (!string.IsNullOrWhiteSpace(selected) &&
            !installed.Contains(selected, StringComparer.OrdinalIgnoreCase) &&
            !catalog.Available.Contains(selected, StringComparer.OrdinalIgnoreCase))
        {
            installed = installed.Append(selected).ToArray();
        }

        foreach (var id in installed)
        {
            ModelBox.Items.Add(ModelPickerItem(id));
        }

        if (catalog.Available.Count > 0)
        {
            ModelBox.Items.Add(new ComboBoxItem
            {
                Content = AvailableSeparator,
                IsEnabled = false,
                IsHitTestVisible = false
            });
            foreach (var id in catalog.Available)
            {
                ModelBox.Items.Add(ModelPickerItem(id));
            }
        }

        if (ModelBox.Items.Count == 0 && !string.IsNullOrWhiteSpace(selected))
        {
            ModelBox.Items.Add(ModelPickerItem(selected));
        }
    }

    private static ComboBoxItem ModelPickerItem(string id) =>
        new() { Content = id, Tag = id };

    private bool SelectModelInPicker(string model)
    {
        if (string.IsNullOrWhiteSpace(model))
        {
            return false;
        }

        foreach (var item in ModelBox.Items)
        {
            if (item is ComboBoxItem combo &&
                string.Equals(combo.Tag as string ?? combo.Content as string, model, StringComparison.OrdinalIgnoreCase))
            {
                ModelBox.SelectedItem = combo;
                return true;
            }
        }

        return false;
    }

    private void EnsureModelInPicker(string model, bool installed)
    {
        if (SelectModelInPicker(model))
        {
            return;
        }

        var item = ModelPickerItem(model);
        if (installed)
        {
            var separator = ModelBox.Items
                .OfType<ComboBoxItem>()
                .FirstOrDefault(i => i.Content as string == AvailableSeparator);
            if (separator is not null)
            {
                ModelBox.Items.Insert(ModelBox.Items.IndexOf(separator), item);
            }
            else
            {
                ModelBox.Items.Insert(0, item);
            }
        }
        else
        {
            ModelBox.Items.Add(item);
        }
    }

    private int FirstSelectableIndex()
    {
        for (var i = 0; i < ModelBox.Items.Count; i++)
        {
            if (ModelBox.Items[i] is ComboBoxItem { IsEnabled: true })
            {
                return i;
            }
        }

        return 0;
    }

    private string? SelectedModelId()
    {
        return ModelBox.SelectedItem switch
        {
            ComboBoxItem { Tag: string tag } => tag,
            ComboBoxItem { Content: string content } => content,
            string id => id,
            _ => null
        };
    }

    private async void ModelBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_suppressModelChange)
        {
            return;
        }

        if (ModelBox.SelectedItem is ComboBoxItem { IsEnabled: false })
        {
            _suppressModelChange = true;
            try
            {
                SelectModelInPicker(App.Services.Settings.Current.SelectedModel);
            }
            finally
            {
                _suppressModelChange = false;
            }

            return;
        }

        var model = SelectedModelId();
        if (string.IsNullOrWhiteSpace(model) ||
            model == AvailableSeparator ||
            model == App.Services.Settings.Current.SelectedModel)
        {
            return;
        }

        App.Services.Settings.Current.SelectedModel = model;
        App.Services.Settings.Save();
        if (_active is not null)
        {
            _active.Model = model;
        }

        try
        {
            await App.Services.Supervisor.RestartWithModelAsync(model, CancellationToken.None);
            await RefreshServerAsync();
        }
        catch (Exception ex)
        {
            App.Services.Supervisor.ReportUiError(ex.Message);
        }
    }

    private async void Send_Click(object sender, RoutedEventArgs e) => await SendAsync();

    private async void PromptBox_KeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key == Windows.System.VirtualKey.Enter &&
            Microsoft.UI.Input.InputKeyboardSource.GetKeyStateForCurrentThread(Windows.System.VirtualKey.Shift)
                .HasFlag(Windows.UI.Core.CoreVirtualKeyStates.Down) == false)
        {
            e.Handled = true;
            if (SendButton.IsEnabled)
            {
                await SendAsync();
            }
        }
    }

    private void Cancel_Click(object sender, RoutedEventArgs e) => _sendCts?.Cancel();

    private void CopyMessage_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not FrameworkElement { Tag: ChatMessage message })
        {
            return;
        }

        var package = new Windows.ApplicationModel.DataTransfer.DataPackage();
        package.SetText(message.Content);
        Windows.ApplicationModel.DataTransfer.Clipboard.SetContent(package);
    }

    private void MessageRow_PointerEntered(object sender, PointerRoutedEventArgs e) =>
        SetHoverButtonsOpacity(sender, 1);

    private void MessageRow_PointerExited(object sender, PointerRoutedEventArgs e) =>
        SetHoverButtonsOpacity(sender, 0);

    private static void SetHoverButtonsOpacity(object sender, double opacity)
    {
        if (sender is not FrameworkElement row)
        {
            return;
        }

        if (row.FindName("CopyButton") is Button copy)
        {
            copy.Opacity = opacity;
        }

        if (row.FindName("SpeakButton") is Button speak)
        {
            speak.Opacity = opacity > 0 && App.Services.Settings.Current.VoiceOutputEnabled ? opacity : 0;
        }
    }

    private async void SpeakMessage_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not FrameworkElement { Tag: ChatMessage message })
        {
            return;
        }

        if (App.Services.Speech.IsSpeaking)
        {
            App.Services.Speech.StopSpeaking();
            return;
        }

        try
        {
            await App.Services.Speech.SpeakAsync(message.Content, CancellationToken.None);
        }
        catch (Exception ex)
        {
            App.Services.Supervisor.ReportUiError(ex.Message);
        }
    }

    private async void Mic_Click(object sender, RoutedEventArgs e)
    {
        MicButton.IsEnabled = false;
        MicIcon.Glyph = ""; // Sync — listening
        try
        {
            var text = await App.Services.Speech.RecognizeOnceAsync(CancellationToken.None);
            if (!string.IsNullOrWhiteSpace(text))
            {
                PromptBox.Text = string.IsNullOrWhiteSpace(PromptBox.Text)
                    ? text
                    : $"{PromptBox.Text} {text}";
                PromptBox.SelectionStart = PromptBox.Text.Length;
            }
        }
        catch (Exception ex)
        {
            App.Services.Supervisor.ReportUiError(ex.Message);
        }
        finally
        {
            MicIcon.Glyph = "";
            MicButton.IsEnabled = true;
        }
    }

    private async Task SendAsync()
    {
        if (_active is null || string.IsNullOrWhiteSpace(PromptBox.Text))
        {
            return;
        }

        if (!App.Services.Supervisor.Status.Ready)
        {
            App.Services.Supervisor.ReportUiError(App.Services.Supervisor.Status.Detail);
            return;
        }

        var active = _active;
        var text = PromptBox.Text.Trim();
        PromptBox.Text = "";
        var user = new ChatMessage { Role = "user", Content = text };
        var assistant = new ChatMessage { Role = "assistant", Content = "", IsPending = true };
        active.Messages.Add(user);
        active.Messages.Add(assistant);
        if (active.Title == "New chat")
        {
            active.Title = text.Length > 42 ? text[..42] : text;
        }

        _messages.Add(user);
        _messages.Add(assistant);
        MessageList.ScrollIntoView(assistant);
        _tools.Clear();
        App.Services.Conversations.Touch(active);

        _sendCts?.Cancel();
        _sendCts = new CancellationTokenSource();
        _sending = true;
        SyncSendButton();
        DeepResearchToggle.IsEnabled = false;
        var isResearch = DeepResearchToggle.IsOn;

        try
        {
            if (isResearch)
            {
                ResearchTimeline.Reset();
                await foreach (var evt in App.Services.Api.StreamResearchAsync(
                    new { query = text, model = ResolveModelId(
                        SelectedModelId() ?? App.Services.Settings.Current.SelectedModel) },
                    _sendCts.Token))
                {
                    ApplyResearchSse(assistant, evt);
                    MessageList.ScrollIntoView(assistant);
                }
            }
            else
            {
                ResearchTimeline.Hide();
                var payload = new
                {
                    model = ResolveModelId(
                        SelectedModelId() ?? App.Services.Settings.Current.SelectedModel),
                    stream = true,
                    temperature = App.Services.Settings.Current.Temperature,
                    max_tokens = App.Services.Settings.Current.MaxTokens,
                    messages = active.Messages
                        .Where(m => m != assistant)
                        .Select(m => new { role = m.Role, content = m.Content })
                        .ToList()
                };

                await foreach (var evt in App.Services.Api.StreamChatAsync(payload, _sendCts.Token))
                {
                    ApplySse(assistant, evt);
                    MessageList.ScrollIntoView(assistant);
                }
            }
        }
        catch (OperationCanceledException)
        {
            assistant.Content += assistant.Content.Length == 0 ? "(stopped)" : "";
        }
        catch (Exception ex)
        {
            assistant.Content = string.IsNullOrEmpty(assistant.Content)
                ? $"The request failed: {ex.Message}"
                : assistant.Content;
            App.Services.Supervisor.ReportUiError(ex.Message);
        }
        finally
        {
            assistant.IsPending = false;
            _sending = false;
            SyncSendButton();
            DeepResearchToggle.IsEnabled = true;
            ResearchTimeline.Finish();
            if (App.Services.Conversations.Items.Contains(active))
            {
                App.Services.Conversations.Touch(active);
            }
        }
    }

    /// <summary>Frames have no <c>event:</c> line — switch on the parsed
    /// JSON's <c>type</c> field. See <c>ResearchModels.cs</c> for the full
    /// set of frame shapes.</summary>
    private void ApplyResearchSse(ChatMessage assistant, SseEvent evt)
    {
        try
        {
            using var doc = JsonDocument.Parse(evt.Data);
            var root = doc.RootElement;
            var type = root.TryGetProperty("type", out var t) ? t.GetString() : null;
            switch (type)
            {
                case "search_call":
                    var query = root.TryGetProperty("arguments", out var args) &&
                        args.TryGetProperty("query", out var q)
                        ? q.GetString() ?? "Searching…"
                        : "Searching…";
                    ResearchTimeline.AddSearchCall(query);
                    break;

                case "search_result":
                    var numHits = root.TryGetProperty("num_hits", out var hits) ? hits.GetInt32() : 0;
                    var titles = root.TryGetProperty("top_titles", out var topTitles)
                        ? topTitles.EnumerateArray().Select(x => x.GetString() ?? "").ToList()
                        : [];
                    ResearchTimeline.CompleteLatestSearch(numHits, titles);
                    break;

                case "synthesis":
                    ResearchTimeline.BeginSynthesizing();
                    if (root.TryGetProperty("text", out var text))
                    {
                        assistant.Content += text.GetString();
                        assistant.IsPending = assistant.Content.Length == 0;
                    }

                    break;

                case "final_sources":
                case "done":
                    if (root.TryGetProperty("sources", out var sources) && sources.GetArrayLength() > 0)
                    {
                        var lines = sources.EnumerateArray()
                            .Select(s => s.TryGetProperty("title", out var title) ? title.GetString() : null)
                            .Where(t => !string.IsNullOrWhiteSpace(t))
                            .Select((t, i) => $"{i + 1}. {t}")
                            .ToList();
                        if (lines.Count > 0 && !assistant.Content.Contains("\n\n## Sources", StringComparison.Ordinal))
                        {
                            assistant.Content += "\n\n## Sources\n" + string.Join("\n", lines);
                        }
                    }

                    break;

                case "error":
                    if (root.TryGetProperty("message", out var message))
                    {
                        assistant.Content += $"\n\n_Research error: {message.GetString()}_";
                    }

                    break;
            }
        }
        catch
        {
            // Non-JSON keepalive chunks are ignored.
        }
    }

    private string ResolveModelId(string selected)
    {
        if (string.IsNullOrWhiteSpace(selected))
        {
            return selected;
        }

        if (selected.Contains(':', StringComparison.Ordinal))
        {
            return selected;
        }

        foreach (var item in ModelBox.Items.OfType<ComboBoxItem>())
        {
            if (item.Content as string == AvailableSeparator)
            {
                continue;
            }

            var id = item.Tag as string ?? item.Content as string ?? "";
            if (id.Equals(selected, StringComparison.OrdinalIgnoreCase) ||
                id.StartsWith(selected + ":", StringComparison.OrdinalIgnoreCase) ||
                id.StartsWith(selected + "-", StringComparison.OrdinalIgnoreCase))
            {
                return id;
            }
        }

        return selected;
    }

    private void ApplySse(ChatMessage assistant, SseEvent evt)
    {
        if (evt.Event is "tool_call_start" or "tool_call_end")
        {
            try
            {
                using var doc = JsonDocument.Parse(evt.Data);
                var root = doc.RootElement;
                var name = root.TryGetProperty("tool", out var tool) ? tool.GetString() ?? "tool" : "tool";
                var existing = _tools.FirstOrDefault(t => t.Tool == name) ?? new ToolCallInfo { Tool = name };
                if (!_tools.Contains(existing))
                {
                    _tools.Add(existing);
                }

                existing.Status = evt.Event == "tool_call_end" ? "success" : "running";
                if (root.TryGetProperty("arguments", out var args))
                {
                    existing.Arguments = args.ToString();
                }

                if (root.TryGetProperty("result", out var result))
                {
                    existing.Result = result.ToString();
                }

                assistant.ToolCalls = _tools.ToList();
            }
            catch
            {
                _tools.Add(new ToolCallInfo { Tool = evt.Event, Status = "running" });
            }

            return;
        }

        try
        {
            using var doc = JsonDocument.Parse(evt.Data);
            if (doc.RootElement.TryGetProperty("choices", out var choices) &&
                choices.GetArrayLength() > 0)
            {
                var delta = choices[0].GetProperty("delta");
                if (delta.TryGetProperty("content", out var content))
                {
                    assistant.Content += content.GetString();
                    assistant.IsPending = assistant.Content.Length == 0;
                    var index = _messages.IndexOf(assistant);
                    if (index >= 0)
                    {
                        _messages[index] = assistant;
                    }
                }
            }
        }
        catch
        {
            // Non-JSON keepalive chunks are ignored.
        }
    }
}

public sealed class SidebarResizeGrip : Grid
{
    public SidebarResizeGrip()
    {
        ProtectedCursor = InputSystemCursor.Create(InputSystemCursorShape.SizeWestEast);
    }
}

/// <summary>
/// Picks the user (plain-text, right-aligned bubble) vs. assistant
/// (Markdown-rendered, no bubble) message template. React's own
/// <c>MessageBubble.tsx</c> draws the same distinction — it only runs
/// ReactMarkdown on the assistant branch, rendering the user's text as-is.
/// </summary>
public sealed class ChatMessageTemplateSelector : DataTemplateSelector
{
    public DataTemplate? UserTemplate { get; set; }
    public DataTemplate? AssistantTemplate { get; set; }

    protected override DataTemplate? SelectTemplateCore(object item) =>
        item is ChatMessage { Role: "user" } ? UserTemplate : AssistantTemplate;

    protected override DataTemplate? SelectTemplateCore(object item, DependencyObject container) =>
        SelectTemplateCore(item);
}
