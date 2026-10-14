using System.Text.RegularExpressions;

namespace OpenJarvis.WinUI.Services;

public static class TomlSettings
{
    public static void EnsureConfigDir()
    {
        Directory.CreateDirectory(AppPaths.ConfigDir);
    }

    public static void SetAllowCloud(bool allow)
    {
        EnsureConfigDir();
        var path = AppPaths.ConfigToml;
        var value = allow ? "true" : "false";
        if (!File.Exists(path))
        {
            File.WriteAllText(path, $"[engine]\ndefault = \"foundry_local\"\nallow_cloud = {value}\n");
            return;
        }

        var text = File.ReadAllText(path);
        if (Regex.IsMatch(text, @"^\s*allow_cloud\s*=", RegexOptions.Multiline))
        {
            text = Regex.Replace(
                text,
                @"^\s*allow_cloud\s*=\s*(true|false).*$",
                $"allow_cloud = {value}",
                RegexOptions.Multiline | RegexOptions.IgnoreCase);
        }
        else if (text.Contains("[engine]"))
        {
            text = text.Replace("[engine]", $"[engine]\nallow_cloud = {value}");
        }
        else
        {
            text = $"[engine]\nallow_cloud = {value}\n\n" + text;
        }

        File.WriteAllText(path, text);
    }

    public static void SetFoundryHost(string host)
    {
        EnsureConfigDir();
        var path = AppPaths.ConfigToml;
        var block = $"[engine.foundry_local]\nhost = \"{host}\"\n";
        if (!File.Exists(path))
        {
            File.WriteAllText(path, $"[engine]\ndefault = \"foundry_local\"\nallow_cloud = false\n\n{block}");
            return;
        }

        var text = File.ReadAllText(path);
        if (Regex.IsMatch(text, @"\[engine\.foundry_local\]"))
        {
            if (Regex.IsMatch(text, @"\[engine\.foundry_local\][^\[]*host\s*="))
            {
                text = Regex.Replace(
                    text,
                    @"(\[engine\.foundry_local\][^\[]*?host\s*=\s*)""[^""]*""",
                    $"$1\"{host}\"",
                    RegexOptions.Singleline);
            }
            else
            {
                text = Regex.Replace(
                    text,
                    @"\[engine\.foundry_local\]",
                    $"[engine.foundry_local]\nhost = \"{host}\"");
            }
        }
        else
        {
            text += "\n" + block;
        }

        File.WriteAllText(path, text);
    }

    public static void SetContextFromMemory(bool enabled)
    {
        EnsureConfigDir();
        var path = AppPaths.ConfigToml;
        var value = enabled ? "true" : "false";
        if (!File.Exists(path))
        {
            File.WriteAllText(path, $"[agent]\ncontext_from_memory = {value}\n");
            return;
        }

        var text = File.ReadAllText(path);
        if (Regex.IsMatch(text, @"^\s*context_from_memory\s*=", RegexOptions.Multiline))
        {
            text = Regex.Replace(
                text,
                @"^\s*context_from_memory\s*=\s*(true|false).*$",
                $"context_from_memory = {value}",
                RegexOptions.Multiline | RegexOptions.IgnoreCase);
        }
        else if (Regex.IsMatch(text, @"^\s*\[agent\]\s*$", RegexOptions.Multiline))
        {
            text = Regex.Replace(
                text,
                @"^\s*\[agent\]\s*$",
                $"[agent]\ncontext_from_memory = {value}",
                RegexOptions.Multiline);
        }
        else
        {
            text = $"[agent]\ncontext_from_memory = {value}\n\n" + text;
        }

        File.WriteAllText(path, text);
    }

    public static void SetMemoryRetrieval(string backend, int topK, double minScore, int maxTokens)
    {
        EnsureConfigDir();
        var path = AppPaths.ConfigToml;
        var minScoreText = minScore.ToString("0.##", System.Globalization.CultureInfo.InvariantCulture);
        var text = File.Exists(path) ? File.ReadAllText(path) : "";

        if (Regex.IsMatch(text, @"^\s*\[tools\.storage\]\s*$", RegexOptions.Multiline))
        {
            text = SetKeyInSection(text, "tools.storage", "default_backend", $"\"{backend}\"");
            text = SetKeyInSection(text, "tools.storage", "context_top_k", topK.ToString());
            text = SetKeyInSection(text, "tools.storage", "context_min_score", minScoreText);
            text = SetKeyInSection(text, "tools.storage", "context_max_tokens", maxTokens.ToString());
        }
        else
        {
            var block =
                "[tools.storage]\n" +
                $"default_backend = \"{backend}\"\n" +
                $"context_top_k = {topK}\n" +
                $"context_min_score = {minScoreText}\n" +
                $"context_max_tokens = {maxTokens}\n";
            text = text.Length == 0 ? block : text.TrimEnd() + "\n\n" + block;
        }

        File.WriteAllText(path, text);
    }

    /// <summary>Replaces <paramref name="key"/> inside an existing <c>[section]</c>
    /// table if present, otherwise inserts it right after that table's header.
    /// Assumes the section header itself already exists in <paramref name="text"/>.</summary>
    private static string SetKeyInSection(string text, string section, string key, string rawValue)
    {
        var sectionHeader = Regex.Escape($"[{section}]");
        var keyPattern = $@"(?m)^(\s*{Regex.Escape(key)}\s*=\s*).*$";

        // Only replace a `key =` line that appears after this section's header
        // and before the next `[` header (or end of file) — a bare top-level
        // Regex.Replace would also match a same-named key in a different table.
        var sectionMatch = Regex.Match(text, $@"{sectionHeader}\s*(?:\r?\n)");
        if (!sectionMatch.Success)
        {
            return text;
        }

        var sectionStart = sectionMatch.Index + sectionMatch.Length;
        var nextHeader = Regex.Match(text[sectionStart..], @"(?m)^\s*\[");
        var sectionEnd = nextHeader.Success ? sectionStart + nextHeader.Index : text.Length;
        var sectionBody = text[sectionStart..sectionEnd];

        if (Regex.IsMatch(sectionBody, keyPattern))
        {
            sectionBody = Regex.Replace(sectionBody, keyPattern, $"${{1}}{rawValue}");
        }
        else
        {
            sectionBody = sectionBody.TrimEnd('\n', '\r') + $"\n{key} = {rawValue}\n";
        }

        return text[..sectionStart] + sectionBody + text[sectionEnd..];
    }

    public static void SetEngineDefault(string engine)
    {
        EnsureConfigDir();
        var path = AppPaths.ConfigToml;
        if (!File.Exists(path))
        {
            File.WriteAllText(path, $"[engine]\ndefault = \"{engine}\"\nallow_cloud = false\n");
            return;
        }

        var text = File.ReadAllText(path);
        if (Regex.IsMatch(text, @"^\s*default\s*=", RegexOptions.Multiline))
        {
            text = Regex.Replace(
                text,
                @"(?m)^(\s*default\s*=\s*)""[^""]*""",
                $"$1\"{engine}\"",
                RegexOptions.Multiline);
        }

        File.WriteAllText(path, text);
    }
}
