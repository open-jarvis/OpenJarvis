namespace OpenJarvis.WinUI.Services;

public static class AppPaths
{
    public static string LocalAppData =>
        Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "OpenJarvis");

    public static string ConfigDir =>
        Environment.GetEnvironmentVariable("OPENJARVIS_HOME") is { Length: > 0 } home
            ? home
            : Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
                ".openjarvis");

    public static string ConfigToml => Path.Combine(ConfigDir, "config.toml");
    public static string ConversationsPath => Path.Combine(ConfigDir, "winui-conversations.json");
    public static string UiSettingsPath => Path.Combine(ConfigDir, "winui-settings.json");
    public static string CloudKeysEnv => Path.Combine(ConfigDir, "cloud-keys.env");
    public static string RuntimeDir => Path.Combine(LocalAppData, "runtime");
    public static string SrcDir => Path.Combine(LocalAppData, "src");
    public static string VenvDir => Path.Combine(LocalAppData, "venv");
    public static string LogsDir => Path.Combine(LocalAppData, "logs");

    public static string JarvisExecutable()
    {
        var scripts = Path.Combine(VenvDir, "Scripts", "jarvis.exe");
        if (File.Exists(scripts))
        {
            return scripts;
        }

        var devRoot = DevProjectRoot();
        if (devRoot is not null)
        {
            // Dev checkouts need `uv run --extra server` so FastAPI/uvicorn are
            // present. The bare .venv console script exits when that extra is missing.
            var uv = FindOnPath("uv.exe");
            if (uv is not null)
            {
                return uv;
            }

            var devJarvis = Path.Combine(devRoot, ".venv", "Scripts", "jarvis.exe");
            if (File.Exists(devJarvis))
            {
                return devJarvis;
            }
        }

        return "";
    }

    /// <summary>
    /// Checkout that contains this app build, when one is present above the
    /// executable. Installed copies under Program Files return null.
    /// </summary>
    public static string? DevProjectRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            var pyproject = Path.Combine(dir.FullName, "pyproject.toml");
            if (File.Exists(pyproject) && IsOpenJarvisProject(pyproject))
            {
                return dir.FullName;
            }

            dir = dir.Parent;
        }

        return null;
    }

    private static bool IsOpenJarvisProject(string pyprojectPath)
    {
        try
        {
            var text = File.ReadAllText(pyprojectPath);
            return text.Contains("openjarvis.cli:main", StringComparison.Ordinal);
        }
        catch (IOException)
        {
            return false;
        }
        catch (UnauthorizedAccessException)
        {
            return false;
        }
    }

    public static string? FindOnPath(string fileName)
    {
        var path = Environment.GetEnvironmentVariable("PATH") ?? "";
        foreach (var dir in path.Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries))
        {
            var candidate = Path.Combine(dir.Trim(), fileName);
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }

        return null;
    }
}
