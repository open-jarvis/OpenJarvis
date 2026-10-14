using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using OpenJarvis.WinUI.Models;

namespace OpenJarvis.WinUI.Views;

/// <summary>Per-agent messaging channels. Slack and SendBlue connect live
/// (no restart) via <c>POST /v1/managed-agents/{id}/channels</c>; every
/// other channel only saves credentials and needs a backend restart to
/// actually start, since the backend resolves channels once at startup.</summary>
public sealed partial class MessagingChannelsPanel : UserControl
{
    private string _agentId = "";
    private List<string> _sendBlueNumbers = [];

    public MessagingChannelsPanel()
    {
        InitializeComponent();
        OtherChannelBox.ItemsSource = OtherChannelCredentials.All
            .Select(c => new ComboBoxItem { Content = c.DisplayName, Tag = c.ChannelType })
            .ToList();
    }

    public string AgentId
    {
        get => _agentId;
        set
        {
            _agentId = value;
            _ = RefreshBindingsAsync();
        }
    }

    private async Task RefreshBindingsAsync()
    {
        if (string.IsNullOrEmpty(_agentId))
        {
            return;
        }

        var bindings = await App.Services.Api.GetChannelBindingsAsync(_agentId, CancellationToken.None);
        BindingsList.ItemsSource = bindings;
        NoBindingsText.Visibility = bindings.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
    }

    private async void RemoveBinding_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { Tag: string bindingId } || string.IsNullOrEmpty(_agentId))
        {
            return;
        }

        await App.Services.Api.UnbindChannelAsync(_agentId, bindingId, CancellationToken.None);
        await RefreshBindingsAsync();
    }

    private async void SlackConnect_Click(object sender, RoutedEventArgs e)
    {
        var botToken = SlackBotTokenBox.Password.Trim();
        var appToken = SlackAppTokenBox.Password.Trim();
        if (botToken.Length == 0 || appToken.Length == 0 || string.IsNullOrEmpty(_agentId))
        {
            return;
        }

        var binding = await App.Services.Api.BindChannelAsync(
            _agentId, "slack", new { bot_token = botToken, app_token = appToken }, "dedicated",
            CancellationToken.None);
        if (binding is null)
        {
            ErrorBar.Message = "Could not connect Slack. Check the tokens and try again.";
            ErrorBar.IsOpen = true;
            return;
        }

        SlackBotTokenBox.Password = "";
        SlackAppTokenBox.Password = "";
        await RefreshBindingsAsync();
    }

    private async void SendBlueVerify_Click(object sender, RoutedEventArgs e)
    {
        var keyId = SendBlueKeyIdBox.Password.Trim();
        var secret = SendBlueSecretBox.Password.Trim();
        if (keyId.Length == 0 || secret.Length == 0)
        {
            return;
        }

        var result = await App.Services.Api.VerifySendBlueAsync(keyId, secret, CancellationToken.None);
        if (result is not { Valid: true } || result.Numbers.Count == 0)
        {
            ErrorBar.Message = "SendBlue verification failed. Check the API key and secret.";
            ErrorBar.IsOpen = true;
            SendBlueNumberBox.IsEnabled = false;
            SendBlueConnectButton.IsEnabled = false;
            return;
        }

        _sendBlueNumbers = result.Numbers;
        SendBlueNumberBox.ItemsSource = _sendBlueNumbers;
        SendBlueNumberBox.SelectedIndex = 0;
        SendBlueNumberBox.IsEnabled = true;
        SendBlueConnectButton.IsEnabled = true;
    }

    private async void SendBlueConnect_Click(object sender, RoutedEventArgs e)
    {
        var keyId = SendBlueKeyIdBox.Password.Trim();
        var secret = SendBlueSecretBox.Password.Trim();
        var number = SendBlueNumberBox.SelectedItem as string;
        if (keyId.Length == 0 || secret.Length == 0 || number is null || string.IsNullOrEmpty(_agentId))
        {
            return;
        }

        var binding = await App.Services.Api.BindChannelAsync(
            _agentId, "sendblue",
            new { api_key_id = keyId, api_secret_key = secret, from_number = number }, "dedicated",
            CancellationToken.None);
        if (binding is null)
        {
            ErrorBar.Message = "Could not connect SendBlue.";
            ErrorBar.IsOpen = true;
            return;
        }

        SendBlueWebhookPanel.Visibility = Visibility.Visible;
        await RefreshBindingsAsync();
    }

    private async void SendBlueRegisterWebhook_Click(object sender, RoutedEventArgs e)
    {
        var keyId = SendBlueKeyIdBox.Password.Trim();
        var secret = SendBlueSecretBox.Password.Trim();
        var url = SendBlueWebhookBox.Text.Trim();
        if (keyId.Length == 0 || secret.Length == 0 || url.Length == 0)
        {
            return;
        }

        SendBlueWebhookStatus.Text = "Registering…";
        var ok = await App.Services.Api.RegisterSendBlueWebhookAsync(keyId, secret, url, CancellationToken.None);
        SendBlueWebhookStatus.Text = ok ? "Webhook registered." : "Could not register the webhook.";
    }

    private void OtherChannelBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        OtherChannelFieldsPanel.Children.Clear();
        if (OtherChannelBox.SelectedItem is not ComboBoxItem { Tag: string channelType })
        {
            return;
        }

        var entry = OtherChannelCredentials.All.First(c => c.ChannelType == channelType);
        foreach (var key in entry.Keys)
        {
            OtherChannelFieldsPanel.Children.Add(new PasswordBox
            {
                Header = key,
                Tag = key,
                PasswordRevealMode = PasswordRevealMode.Peek
            });
        }
    }

    private async void OtherChannelSave_Click(object sender, RoutedEventArgs e)
    {
        if (OtherChannelBox.SelectedItem is not ComboBoxItem { Tag: string channelType } ||
            string.IsNullOrEmpty(_agentId))
        {
            return;
        }

        var keys = OtherChannelFieldsPanel.Children
            .OfType<PasswordBox>()
            .Where(b => b.Password.Trim().Length > 0)
            .ToDictionary(b => (string)b.Tag, b => b.Password.Trim());

        if (keys.Count == 0)
        {
            return;
        }

        await App.Services.Api.SaveToolCredentialsAsync(channelType, keys, CancellationToken.None);
        await App.Services.Api.BindChannelAsync(_agentId, channelType, new { }, "dedicated", CancellationToken.None);
        OtherChannelResultText.Text = "Saved. Restart OpenJarvis to activate this channel.";
        foreach (var box in OtherChannelFieldsPanel.Children.OfType<PasswordBox>())
        {
            box.Password = "";
        }

        await RefreshBindingsAsync();
    }
}
