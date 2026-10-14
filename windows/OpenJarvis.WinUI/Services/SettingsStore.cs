using System.Runtime.InteropServices;
using System.Text.Json;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.Win32;
using OpenJarvis.WinUI.Models;
using Windows.UI;
using Windows.UI.ViewManagement;

namespace OpenJarvis.WinUI.Services;

public sealed class SettingsStore
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        PropertyNameCaseInsensitive = true
    };

    public AppSettings Current { get; private set; } = new();

    public void Load()
    {
        try
        {
            if (File.Exists(AppPaths.UiSettingsPath))
            {
                Current = JsonSerializer.Deserialize<AppSettings>(
                    File.ReadAllText(AppPaths.UiSettingsPath), JsonOptions) ?? new AppSettings();
            }
        }
        catch
        {
            Current = new AppSettings();
        }
    }

    public void Save()
    {
        Persist();
        TomlSettings.SetAllowCloud(Current.AllowCloud);
    }

    public void Persist()
    {
        Directory.CreateDirectory(AppPaths.ConfigDir);
        File.WriteAllText(AppPaths.UiSettingsPath, JsonSerializer.Serialize(Current, JsonOptions));
    }

    /// <summary>
    /// Must run in the <see cref="Application"/> constructor before
    /// <c>InitializeComponent</c>. Setting <see cref="Application.RequestedTheme"/>
    /// later throws COMException 0x80131515.
    /// Unpackaged WinUI does not follow the Windows app theme unless this is set.
    /// </summary>
    public static ApplicationTheme ResolveApplicationTheme(string? theme) =>
        CanonicalTheme(theme) switch
        {
            "Light" => ApplicationTheme.Light,
            "Dark" => ApplicationTheme.Dark,
            _ => SystemPrefersDark() ? ApplicationTheme.Dark : ApplicationTheme.Light
        };

    /// <summary>
    /// Light → Dark → system default → Light, matching the React client's
    /// sidebar theme-toggle cycle (<c>Sidebar.tsx</c>'s <c>nextTheme</c>).
    /// Applies and persists immediately; returns the new theme for callers
    /// that want to update a status label.
    /// </summary>
    public string CycleTheme()
    {
        var next = CanonicalTheme(Current.Theme) switch
        {
            "Light" => "Dark",
            "Dark" => "Default",
            _ => "Light"
        };
        Current.Theme = next;
        ApplyWindowTheme();
        Persist();
        return next;
    }

    public ElementTheme CurrentElementTheme() =>
        CanonicalTheme(Current.Theme) switch
        {
            "Light" => ElementTheme.Light,
            "Dark" => ElementTheme.Dark,
            _ => SystemPrefersDark() ? ElementTheme.Dark : ElementTheme.Light
        };

    public static bool SystemPrefersDark()
    {
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(
                @"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize");
            if (key?.GetValue("AppsUseLightTheme") is int mode)
            {
                return mode == 0;
            }
        }
        catch
        {
            // Registry theme is optional; fall through to light.
        }

        return false;
    }

    public void ApplyWindowTheme(Window? window = null)
    {
        window ??= App.MainWindowInstance;
        if (window?.Content is not FrameworkElement root)
        {
            return;
        }

        var theme = CurrentElementTheme();
        root.RequestedTheme = theme;
        ApplyChromeTheme(root, theme, depth: 0);
        ApplyTitleBar(window, theme == ElementTheme.Dark);
        _appliedSystemDark = SystemPrefersDark();
    }

    public void WatchSystemTheme(Window window)
    {
        if (_watchingSystemTheme)
        {
            return;
        }

        _watchingSystemTheme = true;
        _uiSettings = new UISettings();
        _uiSettings.ColorValuesChanged += (_, _) =>
        {
            window.DispatcherQueue.TryEnqueue(() =>
            {
                if (CanonicalTheme(Current.Theme) is "Light" or "Dark")
                {
                    return;
                }

                if (_appliedSystemDark == SystemPrefersDark())
                {
                    return;
                }

                ApplyWindowTheme(window);
            });
        };
    }

    private static void ApplyChromeTheme(FrameworkElement element, ElementTheme theme, int depth)
    {
        if (depth > 12)
        {
            return;
        }

        if (element is NavigationView or Frame)
        {
            element.RequestedTheme = theme;
        }

        if (element is Panel panel)
        {
            foreach (var child in panel.Children)
            {
                if (child is FrameworkElement frameworkChild)
                {
                    ApplyChromeTheme(frameworkChild, theme, depth + 1);
                }
            }
        }

        if (element is ContentControl control &&
            control.Content is FrameworkElement content &&
            !ReferenceEquals(content, element))
        {
            ApplyChromeTheme(content, theme, depth + 1);
        }
    }

    private static void ApplyTitleBar(Window window, bool dark)
    {
        try
        {
            var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(window);
            var useDark = dark ? 1 : 0;
            _ = DwmSetWindowAttribute(hwnd, DwmwaUseImmersiveDarkMode, ref useDark, sizeof(int));

            var windowId = Microsoft.UI.Win32Interop.GetWindowIdFromWindow(hwnd);
            var titleBar = AppWindow.GetFromWindowId(windowId)?.TitleBar;
            if (titleBar is null)
            {
                return;
            }

            titleBar.PreferredTheme = dark ? TitleBarTheme.Dark : TitleBarTheme.Light;

            var foreground = dark ? Color.FromArgb(255, 255, 255, 255) : Color.FromArgb(255, 32, 32, 32);
            var background = dark ? Color.FromArgb(255, 32, 32, 32) : Color.FromArgb(255, 243, 243, 243);
            var hover = dark ? Color.FromArgb(255, 48, 48, 48) : Color.FromArgb(255, 229, 229, 229);
            var pressed = dark ? Color.FromArgb(255, 64, 64, 64) : Color.FromArgb(255, 217, 217, 217);
            var inactiveForeground = dark ? Color.FromArgb(255, 160, 160, 160) : Color.FromArgb(255, 140, 140, 140);

            titleBar.BackgroundColor = background;
            titleBar.ForegroundColor = foreground;
            titleBar.InactiveBackgroundColor = background;
            titleBar.InactiveForegroundColor = inactiveForeground;
            titleBar.ButtonBackgroundColor = background;
            titleBar.ButtonForegroundColor = foreground;
            titleBar.ButtonHoverBackgroundColor = hover;
            titleBar.ButtonHoverForegroundColor = foreground;
            titleBar.ButtonPressedBackgroundColor = pressed;
            titleBar.ButtonPressedForegroundColor = foreground;
            titleBar.ButtonInactiveBackgroundColor = background;
            titleBar.ButtonInactiveForegroundColor = inactiveForeground;
        }
        catch
        {
            // Title-bar chrome is optional.
        }
    }

    private static string CanonicalTheme(string? theme) =>
        theme?.Trim().ToLowerInvariant() switch
        {
            "light" => "Light",
            "dark" => "Dark",
            _ => "Default"
        };

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int attrValue, int attrSize);

    private const int DwmwaUseImmersiveDarkMode = 20;

    private UISettings? _uiSettings;
    private bool _watchingSystemTheme;
    private bool? _appliedSystemDark;
}
