using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Data;

namespace OpenJarvis.WinUI.Converters;

/// <summary>True → Right, false → Left. Used to align chat-style message
/// bubbles (user right, other-party left) without a WinUI-typed property
/// on the plain data model.</summary>
public sealed class BoolToAlignmentConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, string language) =>
        value is true ? HorizontalAlignment.Right : HorizontalAlignment.Left;

    public object ConvertBack(object value, Type targetType, object parameter, string language) =>
        throw new NotSupportedException();
}
