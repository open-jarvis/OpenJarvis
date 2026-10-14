using System.Collections.ObjectModel;
using System.Text;
using Microsoft.UI.Dispatching;
using OpenJarvis.WinUI.Models;

namespace OpenJarvis.WinUI.Services;

/// <summary>
/// Local, in-memory activity log backing the Logs page — there is no backend
/// log endpoint (confirmed: the React client's Logs page is client-side
/// only). Subscribes to <see cref="BackendSupervisor.StatusChanged"/> itself
/// so <see cref="BackendSupervisor"/> needs no changes; other call sites
/// (chat SSE handling, etc.) call <see cref="Append"/> directly at their
/// existing branch points.
/// </summary>
public sealed class LogService
{
    private const int MaxEntries = 500;
    private readonly DispatcherQueue _dispatcher;
    private string _lastStatusLine = "";

    public LogService(BackendSupervisor supervisor)
    {
        _dispatcher = DispatcherQueue.GetForCurrentThread();
        supervisor.StatusChanged += (_, _) =>
        {
            var status = supervisor.Status;
            var line = string.IsNullOrWhiteSpace(status.Detail)
                ? status.Phase
                : $"{status.Phase}: {status.Detail}";
            if (line == _lastStatusLine)
            {
                return;
            }

            _lastStatusLine = line;
            Append("backend", status.Failed ? "error" : "info", line);
        };
    }

    public ObservableCollection<LogEntry> Entries { get; } = new();

    public void Append(string category, string level, string message)
    {
        void Add()
        {
            Entries.Add(new LogEntry { Category = category, Level = level, Message = message });
            while (Entries.Count > MaxEntries)
            {
                Entries.RemoveAt(0);
            }
        }

        if (_dispatcher.HasThreadAccess)
        {
            Add();
        }
        else
        {
            _dispatcher.TryEnqueue(Add);
        }
    }

    public void Clear() => Entries.Clear();

    public string CopyAllAsText()
    {
        var sb = new StringBuilder();
        foreach (var entry in Entries)
        {
            sb.AppendLine(entry.DisplayLine);
        }

        return sb.ToString();
    }
}
