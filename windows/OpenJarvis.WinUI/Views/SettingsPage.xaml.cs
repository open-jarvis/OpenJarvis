using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using OpenJarvis.WinUI.Models;
using OpenJarvis.WinUI.Services;

namespace OpenJarvis.WinUI.Views;

public sealed partial class SettingsPage : Page
{
    public SettingsPage()
    {
        InitializeComponent();
        Loaded += OnLoaded;
        Loaded += (_, _) =>
        {
            ApplySupervisorStatus();
            App.Services.Supervisor.StatusChanged += OnSupervisorStatusChanged;
        };
        Unloaded += (_, _) => App.Services.Supervisor.StatusChanged -= OnSupervisorStatusChanged;
    }

    private void OnSupervisorStatusChanged(object? sender, EventArgs e) =>
        DispatcherQueue.TryEnqueue(ApplySupervisorStatus);

    /// <summary>
    /// Mirrors <see cref="App.Services.Supervisor"/>'s live status — the
    /// same automatic install/start/model-load sequence <see cref="StatusBanner"/>
    /// already shows, not a separate manually-triggered setup
    /// flow. The former standalone Setup page re-ran that whole sequence by
    /// hand on every click, so it always started from a blank 0% (it never
    /// looked at the supervisor's real state) and finished "instantly" once
    /// clicked, because the supervisor had usually already done the work
    /// in the background seconds after launch.
    /// </summary>
    private void ApplySupervisorStatus()
    {
        var status = App.Services.Supervisor.Status;
        SetupStatusText.Text = string.IsNullOrWhiteSpace(status.Detail)
            ? status.Phase
            : $"{status.Phase} — {status.Detail}";
        SetupStatusIcon.Glyph = status switch
        {
            { Failed: true } => "", // Error
            { Ready: true } => "", // CheckMark
            _ => "" // Sync (in progress)
        };
        RetrySetupButton.IsEnabled = !status.Ready;
    }

    private void RetrySetup_Click(object sender, RoutedEventArgs e) => App.Services.Supervisor.Start();

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        var settings = App.Services.Settings.Current;
        ApiBox.Text = settings.ApiUrl;
        TemperatureBox.Value = settings.Temperature;
        MaxTokensBox.Value = settings.MaxTokens;
        CloudSwitch.IsOn = settings.AllowCloud;
        VoiceOutputSwitch.IsOn = settings.VoiceOutputEnabled;
        VoiceAutoplaySwitch.IsOn = settings.VoiceAutoplay;
        VoiceAutoplaySwitch.IsEnabled = settings.VoiceOutputEnabled;
        foreach (ComboBoxItem item in ThemeBox.Items)
        {
            if (item.Tag as string == settings.Theme)
            {
                ThemeBox.SelectedItem = item;
            }
        }

        ThemeBox.SelectedIndex = ThemeBox.SelectedIndex < 0 ? 0 : ThemeBox.SelectedIndex;
        _themeReady = true;

        var info = await App.Services.Api.GetInfoAsync(CancellationToken.None);
        if (info?.Hardware is { } hw)
        {
            var ep = string.IsNullOrWhiteSpace(hw.ExecutionProvider) ? "unknown" : hw.ExecutionProvider;
            var fallback = hw.ExecutionProviderFallback
                ? "CPU fallback is active. GPU/NPU plugins were not used."
                : "Accelerated execution provider is active.";
            HardwareBlock.Text =
                $"Engine: {info.Engine}\nModel: {info.Model}\nCPU: {hw.CpuBrand}\nArch: {hw.Arch}\n" +
                $"RAM: {hw.RamGb} GB\nGPU: {hw.Gpu?.Name ?? "none"}\nExecution provider: {ep}\n{fallback}";
        }
        else
        {
            HardwareBlock.Text = "Connect to a running backend to read hardware and execution provider.";
        }

        WindowsAiList.ItemsSource = WindowsAiAvailability.Probe()
            .Select(s => $"{s.Api}: {s.ReadyState}. {s.Detail}")
            .ToList();

        await RefreshTavilyStatusAsync();
        await LoadMemoryConfigAsync();
    }

    /// <summary>The server is the only source of truth here — there is no
    /// write endpoint for memory config, so nothing can drift from it.</summary>
    private async Task LoadMemoryConfigAsync()
    {
        var config = await App.Services.Api.GetMemoryConfigAsync(CancellationToken.None);
        _loadedMemoryConfig = config;
        if (config is null)
        {
            MemoryStatusIcon.Glyph = ""; // Info
            MemoryStatusText.Text = "Could not reach the backend to read memory configuration.";
            return;
        }

        MemoryStatusIcon.Glyph = config.Available ? "" : "";
        MemoryStatusText.Text = config.Available
            ? $"{config.BackendType} backend is available."
            : config.Detail ?? "Memory backend is unavailable.";

        MemoryContextSwitch.IsOn = config.ContextFromMemory;
        foreach (ComboBoxItem item in MemoryBackendBox.Items)
        {
            if (item.Tag as string == config.BackendType)
            {
                MemoryBackendBox.SelectedItem = item;
            }
        }

        MemoryBackendBox.SelectedIndex = MemoryBackendBox.SelectedIndex < 0 ? 0 : MemoryBackendBox.SelectedIndex;
        MemoryTopKSlider.Value = config.ContextTopK;
        MemoryMinScoreSlider.Value = config.ContextMinScore;
        MemoryMaxTokensSlider.Value = config.ContextMaxTokens;
    }

    private async Task RefreshTavilyStatusAsync()
    {
        var status = await App.Services.Api.GetToolCredentialStatusAsync("web_search", CancellationToken.None);
        var configured = status.TryGetValue("TAVILY_API_KEY", out var has) && has;
        TavilyStatusText.Text = configured ? "Connected" : "Not configured";
        TavilyRemoveButton.Visibility = configured ? Visibility.Visible : Visibility.Collapsed;
    }

    private async void TavilyKeyBox_LostFocus(object sender, RoutedEventArgs e)
    {
        var value = TavilyKeyBox.Password.Trim();
        TavilyKeyBox.Password = "";
        if (value.Length == 0)
        {
            return;
        }

        await App.Services.Api.SaveToolCredentialsAsync(
            "web_search", new Dictionary<string, string> { ["TAVILY_API_KEY"] = value }, CancellationToken.None);
        await RefreshTavilyStatusAsync();
    }

    private async void TavilyRemove_Click(object sender, RoutedEventArgs e)
    {
        await App.Services.Api.DeleteToolCredentialAsync("web_search", "TAVILY_API_KEY", CancellationToken.None);
        await RefreshTavilyStatusAsync();
    }

    private bool _themeReady;
    private MemoryConfigInfo? _loadedMemoryConfig;

    private void ThemeBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!_themeReady)
        {
            return;
        }

        if (ThemeBox.SelectedItem is ComboBoxItem item &&
            item.Tag is string tag &&
            tag != App.Services.Settings.Current.Theme)
        {
            App.Services.Settings.Current.Theme = tag;
            App.Services.Settings.ApplyWindowTheme();
            App.Services.Settings.Persist();
        }
    }

    private void CloudSwitch_Toggled(object sender, RoutedEventArgs e)
    {
        // Applied on Save so the user makes an explicit choice.
    }

    private void VoiceOutputSwitch_Toggled(object sender, RoutedEventArgs e)
    {
        VoiceAutoplaySwitch.IsEnabled = VoiceOutputSwitch.IsOn;
        if (!VoiceOutputSwitch.IsOn)
        {
            VoiceAutoplaySwitch.IsOn = false;
        }
    }

    private void Save_Click(object sender, RoutedEventArgs e)
    {
        var settings = App.Services.Settings.Current;
        settings.ApiUrl = ApiBox.Text.Trim();
        settings.Temperature = TemperatureBox.Value;
        settings.MaxTokens = (int)MaxTokensBox.Value;
        settings.AllowCloud = CloudSwitch.IsOn;
        App.Services.Settings.Save();
        TomlSettings.SetAllowCloud(settings.AllowCloud);
        App.Services.Api.SetBaseUrl(settings.ApiUrl);
        if (settings.AllowCloud)
        {
            App.Services.Supervisor.ReportUiError(
                "Cloud inference is enabled. Restart OpenJarvis so jarvis serve attaches cloud engines.");
        }

        settings.VoiceOutputEnabled = VoiceOutputSwitch.IsOn;
        settings.VoiceAutoplay = VoiceAutoplaySwitch.IsOn;

        var memoryBackend = (MemoryBackendBox.SelectedItem as ComboBoxItem)?.Tag as string ?? "sqlite";
        var memoryChanged =
            _loadedMemoryConfig is null ||
            _loadedMemoryConfig.ContextFromMemory != MemoryContextSwitch.IsOn ||
            _loadedMemoryConfig.BackendType != memoryBackend ||
            _loadedMemoryConfig.ContextTopK != (int)MemoryTopKSlider.Value ||
            Math.Abs(_loadedMemoryConfig.ContextMinScore - MemoryMinScoreSlider.Value) > 0.001 ||
            _loadedMemoryConfig.ContextMaxTokens != (int)MemoryMaxTokensSlider.Value;

        settings.MemoryContextEnabled = MemoryContextSwitch.IsOn;
        settings.MemoryBackend = memoryBackend;
        settings.MemoryTopK = (int)MemoryTopKSlider.Value;
        settings.MemoryMinScore = MemoryMinScoreSlider.Value;
        settings.MemoryMaxTokens = (int)MemoryMaxTokensSlider.Value;
        App.Services.Settings.Persist();

        if (memoryChanged)
        {
            TomlSettings.SetContextFromMemory(settings.MemoryContextEnabled);
            TomlSettings.SetMemoryRetrieval(
                memoryBackend, settings.MemoryTopK, settings.MemoryMinScore, settings.MemoryMaxTokens);
            App.Services.Supervisor.ReportUiError(
                "Memory settings are saved. Restart OpenJarvis for the new retrieval settings to take effect.");
        }
    }
}
