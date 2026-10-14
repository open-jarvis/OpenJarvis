namespace OpenJarvis.WinUI.Services;

/// <summary>Reads and patches <c>cloud-keys.env</c> — a plain dotenv file
/// (<c>KEY=VALUE</c> per line, <c>#</c> comments) at <see cref="AppPaths.CloudKeysEnv"/>.
/// This is the Python backend's own fallback-read path (<c>routes.py</c>'s
/// <c>/v1/cloud/reload</c>); no backend route writes it, so the desktop app
/// owns writing it directly for the setting to survive a restart. Each save
/// should also call <see cref="JarvisApiClient.ReloadCloudKeysAsync"/> for
/// immediate in-process effect.</summary>
public static class CloudKeysStore
{
    public static Dictionary<string, string> ReadKeys()
    {
        var result = new Dictionary<string, string>(StringComparer.Ordinal);
        var path = AppPaths.CloudKeysEnv;
        if (!File.Exists(path))
        {
            return result;
        }

        foreach (var rawLine in File.ReadAllLines(path))
        {
            var line = rawLine.Trim();
            if (line.Length == 0 || line.StartsWith('#'))
            {
                continue;
            }

            var separator = line.IndexOf('=');
            if (separator <= 0)
            {
                continue;
            }

            var key = line[..separator].Trim();
            var value = line[(separator + 1)..].Trim();
            if (key.Length > 0)
            {
                result[key] = value;
            }
        }

        return result;
    }

    public static void WriteKey(string name, string value)
    {
        Directory.CreateDirectory(AppPaths.ConfigDir);
        var keys = ReadKeys();
        if (string.IsNullOrEmpty(value))
        {
            keys.Remove(name);
        }
        else
        {
            keys[name] = value;
        }

        WriteAll(keys);
    }

    public static void RemoveKey(string name) => WriteKey(name, "");

    private static void WriteAll(Dictionary<string, string> keys)
    {
        var lines = keys.Select(kv => $"{kv.Key}={kv.Value}");
        File.WriteAllLines(AppPaths.CloudKeysEnv, lines);
    }
}
