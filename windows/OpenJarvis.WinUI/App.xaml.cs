using Microsoft.UI.Xaml;
using OpenJarvis.WinUI.Services;

namespace OpenJarvis.WinUI;

public partial class App : Application
{
    public static AppServices Services { get; private set; } = null!;
    private Window? _window;

    public App()
    {
        try
        {
            var earlySettings = new SettingsStore();
            earlySettings.Load();
            RequestedTheme = SettingsStore.ResolveApplicationTheme(earlySettings.Current.Theme);
        }
        catch
        {
            // Theme application is best-effort before XAML loads.
        }

        InitializeComponent();
        UnhandledException += OnUnhandledException;
    }

    public static Window? MainWindowInstance { get; private set; }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        Services = AppServices.Create();
        try
        {
            RuntimeBootstrap.EnsureLocalRuntime();
        }
        catch (Exception ex)
        {
            Services.Supervisor.ReportUiError(
                "Could not stage the OpenJarvis backend runtime: " + ex.Message);
        }

        _window = new MainWindow();
        MainWindowInstance = _window;
        _window.Activate();
        // WinUI resets window chrome during activation. Reapply after the window is shown.
        Services.Settings.ApplyWindowTheme(_window);
        Services.Settings.WatchSystemTheme(_window);
    }

    private static void OnUnhandledException(object sender, Microsoft.UI.Xaml.UnhandledExceptionEventArgs e)
    {
        e.Handled = true;
        Services?.Supervisor.ReportUiError(e.Exception.Message);
    }
}
