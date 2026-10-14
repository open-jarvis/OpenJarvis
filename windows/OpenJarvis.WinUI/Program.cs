using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using WinRT;

namespace OpenJarvis.WinUI;

public static class Program
{
    [STAThread]
    public static void Main(string[] args)
    {
        // Unpackaged WinUI: initialize COM wrappers before Application.Start.
        // Self-contained Windows App SDK does not require Bootstrap.Initialize.
        ComWrappersSupport.InitializeComWrappers();
        try
        {
            Application.Start(InitializeApp);
        }
        catch (Exception ex)
        {
            System.Diagnostics.Debug.WriteLine(ex);
            throw;
        }
    }

    private static void InitializeApp(ApplicationInitializationCallbackParams initParams)
    {
        var context = new DispatcherQueueSynchronizationContext(
            DispatcherQueue.GetForCurrentThread());
        SynchronizationContext.SetSynchronizationContext(context);
        var app = new App();
    }
}
