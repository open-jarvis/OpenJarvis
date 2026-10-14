namespace OpenJarvis.WinUI.Models;

/// <summary>
/// One line in the Logs page. Mirrors the React client's client-side-only
/// log (<c>LogsPage.tsx</c> reading an in-memory store) — there is no
/// backend log endpoint to back this; entries come entirely from what this
/// app itself observes (backend status changes, chat/tool activity).
/// </summary>
public sealed class LogEntry
{
    public DateTimeOffset Timestamp { get; init; } = DateTimeOffset.Now;
    public string Category { get; init; } = "";
    public string Level { get; init; } = "info";
    public string Message { get; init; } = "";

    public string DisplayLine =>
        $"{Timestamp:HH:mm:ss} [{Category}] {Message}";
}
