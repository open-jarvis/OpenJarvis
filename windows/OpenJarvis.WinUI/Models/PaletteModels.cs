namespace OpenJarvis.WinUI.Models;

public enum PaletteItemKind
{
    Page,
    Conversation,
    Model,
    Agent
}

/// <summary>One row in the Ctrl+K quick switcher. <see cref="Payload"/> carries
/// whatever the activation handler needs: the nav tag string for a Page, the
/// <c>Conversation</c> object, the model id string, or the agent id string.</summary>
public sealed class PaletteItem
{
    public required PaletteItemKind Kind { get; init; }
    public required string Title { get; init; }
    public string Subtitle { get; init; } = "";
    public string Glyph { get; init; } = "";
    public object? Payload { get; init; }
}
