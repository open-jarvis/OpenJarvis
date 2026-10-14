using Windows.Foundation.Metadata;

namespace OpenJarvis.WinUI.Services;

public sealed class WindowsAiStatus
{
    public bool Present { get; init; }
    public string Api { get; init; } = "";
    public string ReadyState { get; init; } = "Unavailable";
    public string Detail { get; init; } = "";
}

public static class WindowsAiAvailability
{
    public static IReadOnlyList<WindowsAiStatus> Probe()
    {
        return
        [
            ProbeType(
                "Microsoft.Windows.AI.Generative.LanguageModel",
                "Windows AI text / Phi Silica"),
            ProbeType(
                "Windows.AI.MachineLearning.LearningModel",
                "Windows.AI.MachineLearning (WinML)"),
            ProbeType(
                "Microsoft.Windows.AI.MachineLearning.LearningModelSession",
                "Windows App SDK Windows ML")
        ];
    }

    private static WindowsAiStatus ProbeType(string typeName, string label)
    {
        try
        {
            var present = ApiInformation.IsTypePresent(typeName);
            return new WindowsAiStatus
            {
                Present = present,
                Api = label,
                ReadyState = present ? "Present" : "Not present",
                Detail = present
                    ? "Runtime type is available. OpenJarvis chat still uses Foundry Local, not this API."
                    : "This Windows AI API is not available on this OS build."
            };
        }
        catch (Exception ex)
        {
            return new WindowsAiStatus
            {
                Present = false,
                Api = label,
                ReadyState = "Check failed",
                Detail = ex.Message
            };
        }
    }
}
