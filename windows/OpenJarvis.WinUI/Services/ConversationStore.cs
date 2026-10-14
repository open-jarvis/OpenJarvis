using System.Collections.ObjectModel;
using System.Text.Json;
using OpenJarvis.WinUI.Models;

namespace OpenJarvis.WinUI.Services;

public sealed class ConversationStore
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        PropertyNameCaseInsensitive = true
    };

    public ObservableCollection<Conversation> Items { get; } = [];
    public Conversation? Active { get; private set; }

    public event EventHandler? ActiveChanged;

    public void Load()
    {
        Items.Clear();
        Active = null;
        if (!File.Exists(AppPaths.ConversationsPath))
        {
            return;
        }

        try
        {
            var file = JsonSerializer.Deserialize<ConversationStoreFile>(
                File.ReadAllText(AppPaths.ConversationsPath), JsonOptions)
                ?? new ConversationStoreFile();
            foreach (var conversation in file.Conversations.Values.OrderByDescending(c => c.UpdatedAt))
            {
                Items.Add(conversation);
            }

            if (file.ActiveId is not null)
            {
                Active = Items.FirstOrDefault(c => c.Id == file.ActiveId);
            }

            Active ??= Items.FirstOrDefault();
        }
        catch
        {
            // Keep an empty store rather than crashing the UI.
        }
    }

    public void Save()
    {
        Directory.CreateDirectory(AppPaths.ConfigDir);
        var file = new ConversationStoreFile
        {
            Version = 1,
            ActiveId = Active?.Id,
            Conversations = Items.ToDictionary(c => c.Id)
        };
        File.WriteAllText(AppPaths.ConversationsPath, JsonSerializer.Serialize(file, JsonOptions));
    }

    public Conversation NewConversation(string model)
    {
        var conversation = new Conversation { Model = model };
        Items.Insert(0, conversation);
        Active = conversation;
        Save();
        ActiveChanged?.Invoke(this, EventArgs.Empty);
        return conversation;
    }

    public void Select(Conversation conversation)
    {
        if (Active == conversation)
        {
            return;
        }

        Active = conversation;
        Save();
        ActiveChanged?.Invoke(this, EventArgs.Empty);
    }

    public void Rename(Conversation conversation, string title)
    {
        var trimmed = title.Trim();
        if (trimmed.Length == 0 || conversation.Title == trimmed)
        {
            return;
        }

        conversation.Title = trimmed;
        Save();
    }

    public void Touch(Conversation conversation)
    {
        conversation.UpdatedAt = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        if (Items.Contains(conversation))
        {
            Items.Remove(conversation);
            Items.Insert(0, conversation);
        }

        Save();
    }

    public void Delete(Conversation conversation)
    {
        var index = -1;
        for (var i = 0; i < Items.Count; i++)
        {
            if (Items[i].Id == conversation.Id)
            {
                index = i;
                break;
            }
        }

        if (index < 0)
        {
            return;
        }

        var removingActive = Active?.Id == conversation.Id;
        Items.RemoveAt(index);
        if (removingActive)
        {
            Active = Items.Count == 0 ? null : Items[Math.Min(index, Items.Count - 1)];
        }

        Save();
        if (removingActive)
        {
            ActiveChanged?.Invoke(this, EventArgs.Empty);
        }
    }
}
