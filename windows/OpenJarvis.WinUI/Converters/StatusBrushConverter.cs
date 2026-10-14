using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Data;
using Microsoft.UI.Xaml.Media;

namespace OpenJarvis.WinUI.Converters;

/// <summary>
/// Resolves a status-brush resource key (e.g. "StatusSuccessBrush", see
/// <c>Styles/AppStyles.xaml</c>) to the actual <see cref="Brush"/>. Models
/// expose the key as a plain string (so they stay free of UI-framework
/// types); this converter is the one place that looks it up. Reused by
/// every status-dot across the shell (tool-activity cards now, Dashboard/
/// Data Sources/Agents rows later).
/// </summary>
public sealed class StatusBrushConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, string language)
    {
        if (value is string key &&
            Application.Current.Resources.TryGetValue(key, out var resource) &&
            resource is Brush brush)
        {
            return brush;
        }

        return Application.Current.Resources["StatusIdleBrush"];
    }

    public object ConvertBack(object value, Type targetType, object parameter, string language) =>
        throw new NotSupportedException();
}
