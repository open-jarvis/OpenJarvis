using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Automation.Peers;
using Microsoft.UI.Xaml.Controls;
using OpenJarvis.WinUI.Models;

namespace OpenJarvis.WinUI.Views;

/// <summary>
/// The single place backend status and errors are surfaced: red while
/// <see cref="BackendStatus.Failed"/>, yellow while setting up, green once
/// ready. Dismissing hides it until the severity changes, or until the next
/// error is reported.
/// </summary>
public sealed partial class StatusBanner : UserControl
{
    private InfoBarSeverity? _dismissedSeverity;

    public StatusBanner()
    {
        InitializeComponent();
        Loaded += (_, _) =>
        {
            App.Services.Supervisor.StatusChanged += OnStatusChanged;
            Apply(isNewEvent: false);
        };
        Unloaded += (_, _) => App.Services.Supervisor.StatusChanged -= OnStatusChanged;
    }

    private void OnStatusChanged(object? sender, EventArgs e) =>
        DispatcherQueue.TryEnqueue(() => Apply(isNewEvent: true));

    private void Apply(bool isNewEvent)
    {
        var status = App.Services.Supervisor.Status;
        var severity = status switch
        {
            { Failed: true } => InfoBarSeverity.Error,
            { Ready: true } => InfoBarSeverity.Success,
            _ => InfoBarSeverity.Warning
        };

        if (_dismissedSeverity is { } dismissed &&
            (dismissed != severity || (isNewEvent && severity == InfoBarSeverity.Error)))
        {
            _dismissedSeverity = null;
        }

        Bar.Severity = severity;
        Bar.Title = severity switch
        {
            InfoBarSeverity.Error => "OpenJarvis needs attention",
            InfoBarSeverity.Success => "OpenJarvis is ready",
            _ => string.IsNullOrWhiteSpace(status.Phase) ? "Setting up OpenJarvis" : status.Phase
        };
        Bar.Message = severity == InfoBarSeverity.Success && status.Detail == "OpenJarvis is ready."
            ? ""
            : status.Detail;
        Bar.IconSource = severity == InfoBarSeverity.Warning
            ? new FontIconSource { Glyph = "\uE895" }
            : null;
        AutomationProperties.SetLiveSetting(
            Bar,
            severity == InfoBarSeverity.Error ? AutomationLiveSetting.Assertive : AutomationLiveSetting.Polite);
        Bar.IsOpen = _dismissedSeverity is null;
    }

    private void Bar_CloseButtonClick(InfoBar sender, object args) =>
        _dismissedSeverity = sender.Severity;
}
