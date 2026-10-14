using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using OpenJarvis.WinUI.Models;
using OpenJarvis.WinUI.Services;

namespace OpenJarvis.WinUI.Views;

/// <summary>Cloud inference provider API keys — one row per
/// <see cref="CloudProviderKey"/>. Save-on-blur, no page-level Save button:
/// each row writes <c>cloud-keys.env</c> via <see cref="CloudKeysStore"/>
/// and calls <c>/v1/cloud/reload</c> for immediate effect, independent of
/// the rest of Settings.</summary>
public sealed partial class CloudModelsPanel : UserControl
{
    private readonly List<CloudKeyRow> _rows = CloudProviderKey.All
        .Select(p => new CloudKeyRow { ProviderName = p.ProviderName, EnvVarName = p.EnvVarName })
        .ToList();

    public CloudModelsPanel()
    {
        InitializeComponent();
        ProviderList.ItemsSource = _rows;
        Loaded += (_, _) => RefreshConnectedState();
    }

    private void RefreshConnectedState()
    {
        var saved = CloudKeysStore.ReadKeys();
        foreach (var row in _rows)
        {
            row.IsConnected = saved.TryGetValue(row.EnvVarName, out var value) && !string.IsNullOrEmpty(value);
        }
    }

    private async void KeyBox_LostFocus(object sender, RoutedEventArgs e)
    {
        if (sender is not PasswordBox box || box.Tag is not string envVar)
        {
            return;
        }

        var value = box.Password;
        if (string.IsNullOrWhiteSpace(value))
        {
            // Nothing typed — leave the existing key (if any) untouched.
            return;
        }

        await SaveKeyAsync(envVar, value.Trim());
        box.Password = "";
    }

    private async void Remove_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button button || button.Tag is not string envVar)
        {
            return;
        }

        await SaveKeyAsync(envVar, "");
    }

    private async Task SaveKeyAsync(string envVar, string value)
    {
        ErrorBar.IsOpen = false;
        try
        {
            CloudKeysStore.WriteKey(envVar, value);
            var result = await App.Services.Api.ReloadCloudKeysAsync(
                new Dictionary<string, string> { [envVar] = value }, CancellationToken.None);
            if (result?.Status == "error")
            {
                ErrorBar.Message = result.Message ?? "Failed to reload cloud keys.";
                ErrorBar.IsOpen = true;
            }
        }
        catch (Exception ex)
        {
            ErrorBar.Message = ex.Message;
            ErrorBar.IsOpen = true;
        }
        finally
        {
            RefreshConnectedState();
        }
    }
}
