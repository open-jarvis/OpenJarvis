using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;

namespace OpenJarvis.WinUI.Views;

public enum SetupStepState
{
    Pending,
    Active,
    Done,
    Failed
}

public sealed partial class SetupStepRow : UserControl
{
    public SetupStepRow()
    {
        InitializeComponent();
    }

    public string Label
    {
        get => LabelText.Text;
        set
        {
            LabelText.Text = value;
            AutomationProperties.SetName(this, value);
        }
    }

    public string Glyph
    {
        get => IdleGlyph.Glyph;
        set
        {
            IdleGlyph.Glyph = value;
            DoneGlyph.Glyph = value;
        }
    }

    public void Update(SetupStepState state, string detail)
    {
        var done = state == SetupStepState.Done;
        var active = state is SetupStepState.Active or SetupStepState.Failed;

        ActiveBackground.Visibility = active ? Visibility.Visible : Visibility.Collapsed;
        DoneBackground.Visibility = done ? Visibility.Visible : Visibility.Collapsed;
        IconIdleTile.Visibility = done ? Visibility.Collapsed : Visibility.Visible;
        IconDoneTile.Visibility = done ? Visibility.Visible : Visibility.Collapsed;
        IdleGlyph.Visibility = done ? Visibility.Collapsed : Visibility.Visible;
        DoneGlyph.Visibility = done ? Visibility.Visible : Visibility.Collapsed;

        PendingDot.Visibility = state == SetupStepState.Pending ? Visibility.Visible : Visibility.Collapsed;
        ActiveRing.IsActive = state == SetupStepState.Active;
        ActiveRing.Visibility = state == SetupStepState.Active ? Visibility.Visible : Visibility.Collapsed;
        DoneMark.Visibility = done ? Visibility.Visible : Visibility.Collapsed;
        FailedMark.Visibility = state == SetupStepState.Failed ? Visibility.Visible : Visibility.Collapsed;

        var text = state switch
        {
            SetupStepState.Done => "Ready",
            SetupStepState.Pending => "Waiting…",
            _ => detail
        };
        DetailText.Text = text;
        ToolTipService.SetToolTip(DetailText, state is SetupStepState.Active or SetupStepState.Failed ? detail : null);
        AutomationProperties.SetHelpText(this, text);
    }
}
