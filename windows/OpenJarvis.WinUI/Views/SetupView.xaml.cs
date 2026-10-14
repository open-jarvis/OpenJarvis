using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using OpenJarvis.WinUI.Models;

namespace OpenJarvis.WinUI.Views;

/// <summary>
/// Launch-time setup screen, the WinUI counterpart of the React client's
/// <c>SetupScreen</c> + <c>InferenceSourceSetup</c>. Foundry Local is never
/// installed, started, or asked to download a model until the user consents;
/// after that every launch shows live per-step progress from
/// <see cref="Services.BackendSupervisor"/> and hands off once it is ready.
/// </summary>
public sealed partial class SetupView : UserControl
{
    private static readonly TimeSpan HandOffDelay = TimeSpan.FromMilliseconds(600);
    private bool _handedOff;
    private bool _recovering;
    private bool _listening;

    public SetupView()
    {
        InitializeComponent();
        TrySetLogo();
    }

    private void TrySetLogo()
    {
        try
        {
            var logoPath = Path.Combine(AppContext.BaseDirectory, "Assets", "OpenJarvis_Circular_Logo.png");
            if (!File.Exists(logoPath))
            {
                return;
            }

            LogoMark.Fill = new ImageBrush
            {
                ImageSource = new BitmapImage(new Uri(logoPath)),
                Stretch = Stretch.UniformToFill,
            };
        }
        catch
        {
            // The header mark is decorative.
        }
    }

    public event EventHandler? Completed;

    public void Begin()
    {
        _handedOff = false;
        if (App.Services.Settings.Current.LocalSetupConsented)
        {
            ShowProgress();
            App.Services.Supervisor.Start();
        }
        else
        {
            ShowConsent();
        }
    }

    private void ShowConsent()
    {
        StopListening();
        var model = App.Services.Settings.Current.SelectedModel;
        ConsentDetailText.Text =
            "OpenJarvis will install and start Foundry Local if needed, and may download " +
            (string.IsNullOrWhiteSpace(model) ? "one model" : $"the model {model}") +
            " for this computer. Model downloads can use several gigabytes of disk space and network data.";
        ConsentErrorText.Visibility = Visibility.Collapsed;
        ConsentButton.IsEnabled = true;
        ProgressPanel.Visibility = Visibility.Collapsed;
        ConsentPanel.Visibility = Visibility.Visible;
    }

    private void ShowProgress()
    {
        ConsentPanel.Visibility = Visibility.Collapsed;
        ProgressPanel.Visibility = Visibility.Visible;
        RecoveryErrorText.Visibility = Visibility.Collapsed;
        StartListening();
        ApplyStatus();
    }

    private void StartListening()
    {
        if (_listening)
        {
            return;
        }

        _listening = true;
        App.Services.Supervisor.StatusChanged += OnStatusChanged;
    }

    private void StopListening()
    {
        if (!_listening)
        {
            return;
        }

        _listening = false;
        App.Services.Supervisor.StatusChanged -= OnStatusChanged;
    }

    private void OnStatusChanged(object? sender, EventArgs e) =>
        DispatcherQueue.TryEnqueue(ApplyStatus);

    private void ApplyStatus()
    {
        if (!_listening)
        {
            return;
        }

        var status = App.Services.Supervisor.Status;
        var step = status.Step;
        var detail = string.IsNullOrWhiteSpace(status.Detail) ? status.Phase : status.Detail;

        EngineRow.Update(StateFor(SetupStep.Engine, status), DefaultDetail(SetupStep.Engine, step, detail));
        ModelRow.Update(StateFor(SetupStep.Model, status), DefaultDetail(SetupStep.Model, step, detail));
        ServerRow.Update(StateFor(SetupStep.Server, status), DefaultDetail(SetupStep.Server, step, detail));

        ErrorBar.IsOpen = status.Failed;
        ErrorBar.Message = status.Failed ? status.Detail : "";
        RetryButton.Visibility = status.Failed ? Visibility.Visible : Visibility.Collapsed;
        Grid.SetColumnSpan(ChangeSourceButton, status.Failed ? 1 : 2);
        Grid.SetColumn(ChangeSourceButton, status.Failed ? 1 : 0);
        ChangeSourceButton.Visibility = step == SetupStep.Done ? Visibility.Collapsed : Visibility.Visible;
        ChangeSourceButton.IsEnabled = !_recovering;
        StepProgress.Visibility = status.Failed ? Visibility.Collapsed : Visibility.Visible;
        StepProgress.Value = (int)step;

        SubtitleText.Text = step == SetupStep.Done
            ? "Ready"
            : status.Phase == "Checking backend"
                ? "Checking your saved setup…"
                : "Setting up your local AI…";

        if (step == SetupStep.Done && !status.Failed && !_handedOff)
        {
            _handedOff = true;
            _ = HandOffAsync();
        }
    }

    private async Task HandOffAsync()
    {
        await Task.Delay(HandOffDelay);
        StopListening();
        Completed?.Invoke(this, EventArgs.Empty);
    }

    private static SetupStepState StateFor(SetupStep row, BackendStatus status)
    {
        if (status.Step > row)
        {
            return SetupStepState.Done;
        }

        if (status.Step < row)
        {
            return SetupStepState.Pending;
        }

        return status.Failed ? SetupStepState.Failed : SetupStepState.Active;
    }

    private static string DefaultDetail(SetupStep row, SetupStep active, string detail)
    {
        if (row == active && !string.IsNullOrWhiteSpace(detail))
        {
            return detail;
        }

        return row switch
        {
            SetupStep.Engine => "Starting Foundry Local…",
            SetupStep.Model => "Loading model…",
            _ => "Starting server…"
        };
    }

    private void ConsentButton_Click(object sender, RoutedEventArgs e)
    {
        ConsentButton.IsEnabled = false;
        try
        {
            App.Services.Settings.Current.LocalSetupConsented = true;
            App.Services.Settings.Save();
        }
        catch (Exception ex)
        {
            App.Services.Settings.Current.LocalSetupConsented = false;
            ConsentErrorText.Text = "Could not save your choice: " + ex.Message;
            ConsentErrorText.Visibility = Visibility.Visible;
            ConsentButton.IsEnabled = true;
            return;
        }

        ShowProgress();
        App.Services.Supervisor.Start();
    }

    private void RetryButton_Click(object sender, RoutedEventArgs e)
    {
        RecoveryErrorText.Visibility = Visibility.Collapsed;
        App.Services.Supervisor.Start();
    }

    private async void ChangeSourceButton_Click(object sender, RoutedEventArgs e)
    {
        _recovering = true;
        ChangeSourceButton.IsEnabled = false;
        ChangeSourceButton.Content = "Stopping setup…";
        RecoveryErrorText.Visibility = Visibility.Collapsed;
        try
        {
            StopListening();
            await App.Services.Supervisor.StopAsync();
            App.Services.Settings.Current.LocalSetupConsented = false;
            App.Services.Settings.Save();
            ShowConsent();
        }
        catch (Exception ex)
        {
            StartListening();
            RecoveryErrorText.Text = ex.Message;
            RecoveryErrorText.Visibility = Visibility.Visible;
        }
        finally
        {
            _recovering = false;
            ChangeSourceButton.Content = "Change inference source";
            ChangeSourceButton.IsEnabled = true;
        }
    }

    private void Scroller_SizeChanged(object sender, SizeChangedEventArgs e)
    {
        ContentHost.MinHeight = e.NewSize.Height;
    }
}
