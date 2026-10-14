using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using OpenJarvis.WinUI.Models;

namespace OpenJarvis.WinUI.Views;

public sealed partial class CreateAgentDialog : ContentDialog
{
    private const string AvailableSeparator = "── Available to download ──";

    private int _step;
    private bool _suppressModelChange;
    private AgentTemplate? _selectedTemplate;
    private List<ToolCatalogItem> _allTools = [];

    /// <summary>The create-agent request body, set once the wizard
    /// completes (dialog result Primary on the final step).</summary>
    public object? Result { get; private set; }

    public CreateAgentDialog()
    {
        InitializeComponent();
        Loaded += async (_, _) => await LoadCatalogAsync();
    }

    private async Task LoadCatalogAsync()
    {
        var templates = await App.Services.Api.GetAgentTemplatesAsync(CancellationToken.None);
        TemplateList.ItemsSource = templates;

        _allTools = (await App.Services.Api.GetToolCatalogAsync(CancellationToken.None)).ToList();
        ToolCategoryList.ItemsSource = _allTools
            .GroupBy(t => string.IsNullOrWhiteSpace(t.Category) ? "other" : t.Category)
            .OrderBy(g => g.Key)
            .Select(g => new ToolCatalogCategory { Category = g.Key, Items = g.ToList() })
            .ToList();

        var catalog = await App.Services.Foundry.ListCatalogAsync(CancellationToken.None);
        var apiModels = await App.Services.Api.GetModelsAsync(CancellationToken.None);
        PopulateModelPicker(catalog, apiModels);

        ScheduleBox.SelectedIndex = 0;
        MemoryExtractionBox.SelectedIndex = 0;
        ObservationCompressionBox.SelectedIndex = 0;
        RetrievalStrategyBox.SelectedIndex = 0;
        TaskDecompositionBox.SelectedIndex = 0;
    }

    private void TemplateList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (TemplateList.SelectedItem is not AgentTemplate template)
        {
            return;
        }

        ApplyTemplate(template);
    }

    private void StartFromScratch_Click(object sender, RoutedEventArgs e)
    {
        TemplateList.SelectedItem = null;
        _selectedTemplate = null;
        AdvanceStep();
    }

    private void ApplyTemplate(AgentTemplate template)
    {
        _selectedTemplate = template;
        NameBox.Text = template.Name;
        foreach (var tool in _allTools)
        {
            tool.IsSelected = template.Tools.Contains(tool.Name, StringComparer.OrdinalIgnoreCase);
        }

        SelectComboTag(ScheduleBox, template.ScheduleType);
        ScheduleValueBox.Text = template.ScheduleValue ?? "";
        MaxTurnsBox.Value = template.MaxTurns;
        TemperatureBox.Value = template.Temperature;
        AdvanceStep();
    }

    private void PopulateModelPicker(FoundryModelCatalog catalog, IReadOnlyList<string> apiModels)
    {
        var installed = catalog.Installed.Count > 0
            ? catalog.Installed
            : apiModels;
        var selected = App.Services.Settings.Current.SelectedModel;
        if (!string.IsNullOrWhiteSpace(selected) &&
            !installed.Contains(selected, StringComparer.OrdinalIgnoreCase) &&
            !catalog.Available.Contains(selected, StringComparer.OrdinalIgnoreCase))
        {
            installed = installed.Append(selected).ToArray();
        }

        _suppressModelChange = true;
        try
        {
            ModelBox.ItemsSource = null;
            ModelBox.Items.Clear();
            foreach (var id in installed)
            {
                ModelBox.Items.Add(new ComboBoxItem { Content = id, Tag = id });
            }

            if (catalog.Available.Count > 0)
            {
                ModelBox.Items.Add(new ComboBoxItem
                {
                    Content = AvailableSeparator,
                    IsEnabled = false,
                    IsHitTestVisible = false
                });
                foreach (var id in catalog.Available)
                {
                    ModelBox.Items.Add(new ComboBoxItem { Content = id, Tag = id });
                }
            }

            if (ModelBox.Items.Count == 0 && !string.IsNullOrWhiteSpace(selected))
            {
                ModelBox.Items.Add(new ComboBoxItem { Content = selected, Tag = selected });
            }

            if (!SelectModelInPicker(selected))
            {
                ModelBox.SelectedIndex = FirstSelectableIndex();
            }
        }
        finally
        {
            _suppressModelChange = false;
        }
    }

    private bool SelectModelInPicker(string model)
    {
        if (string.IsNullOrWhiteSpace(model))
        {
            return false;
        }

        foreach (var item in ModelBox.Items)
        {
            if (item is ComboBoxItem combo &&
                combo.IsEnabled &&
                string.Equals(combo.Tag as string ?? combo.Content as string, model, StringComparison.OrdinalIgnoreCase))
            {
                ModelBox.SelectedItem = combo;
                return true;
            }
        }

        return false;
    }

    private int FirstSelectableIndex()
    {
        for (var i = 0; i < ModelBox.Items.Count; i++)
        {
            if (ModelBox.Items[i] is ComboBoxItem { IsEnabled: true })
            {
                return i;
            }
        }

        return -1;
    }

    private string? SelectedModelId()
    {
        return ModelBox.SelectedItem switch
        {
            ComboBoxItem { IsEnabled: false } => null,
            ComboBoxItem { Tag: string tag } => tag,
            ComboBoxItem { Content: string content } => content,
            string id => id,
            _ => null
        };
    }

    private void ModelBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_suppressModelChange || ModelBox.SelectedItem is not ComboBoxItem { IsEnabled: false })
        {
            return;
        }

        _suppressModelChange = true;
        try
        {
            if (!SelectModelInPicker(App.Services.Settings.Current.SelectedModel))
            {
                ModelBox.SelectedIndex = FirstSelectableIndex();
            }
        }
        finally
        {
            _suppressModelChange = false;
        }
    }

    private static void SelectComboTag(ComboBox box, string tag)
    {
        foreach (var item in box.Items.OfType<ComboBoxItem>())
        {
            if (string.Equals(item.Tag as string, tag, StringComparison.OrdinalIgnoreCase))
            {
                box.SelectedItem = item;
                return;
            }
        }
    }

    private void ScheduleBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        var tag = (ScheduleBox.SelectedItem as ComboBoxItem)?.Tag as string;
        ScheduleValueBox.Visibility = tag is "interval" or "cron" ? Visibility.Visible : Visibility.Collapsed;
        ScheduleValueBox.Header = tag == "cron" ? "Cron expression" : "Interval (seconds)";
    }

    private void ContentDialog_PrimaryButtonClick(ContentDialog sender, ContentDialogButtonClickEventArgs args)
    {
        if (_step < 3)
        {
            args.Cancel = true;
            AdvanceStep();
            return;
        }

        Result = BuildRequestBody();
    }

    private void AdvanceStep()
    {
        var steps = new[] { Step0, Step1, Step2, Step3 };
        steps[_step].Visibility = Visibility.Collapsed;
        _step++;
        steps[_step].Visibility = Visibility.Visible;
        PrimaryButtonText = _step == 3 ? "Create" : "Next";
    }

    private object BuildRequestBody()
    {
        var scheduleType = (ScheduleBox.SelectedItem as ComboBoxItem)?.Tag as string ?? "manual";
        var memoryExtraction = (MemoryExtractionBox.SelectedItem as ComboBoxItem)?.Tag as string;
        var observationCompression = (ObservationCompressionBox.SelectedItem as ComboBoxItem)?.Tag as string;
        var retrievalStrategy = (RetrievalStrategyBox.SelectedItem as ComboBoxItem)?.Tag as string;
        var taskDecomposition = (TaskDecompositionBox.SelectedItem as ComboBoxItem)?.Tag as string;
        var selectedTools = _allTools.Where(t => t.IsSelected).Select(t => t.Name).ToList();

        var config = new Dictionary<string, object?>
        {
            ["instruction"] = InstructionBox.Text,
            ["tools"] = selectedTools,
            ["model"] = SelectedModelId(),
            ["schedule_type"] = scheduleType,
            ["schedule_value"] = string.IsNullOrWhiteSpace(ScheduleValueBox.Text) ? null : ScheduleValueBox.Text,
            ["max_turns"] = (int)MaxTurnsBox.Value,
            ["temperature"] = TemperatureBox.Value,
            ["memory_extraction"] = memoryExtraction,
            ["observation_compression"] = observationCompression,
            ["retrieval_strategy"] = retrievalStrategy,
            ["task_decomposition"] = taskDecomposition,
        };
        if (!double.IsNaN(BudgetBox.Value) && BudgetBox.Value > 0)
        {
            config["budget"] = BudgetBox.Value;
        }

        return new
        {
            name = string.IsNullOrWhiteSpace(NameBox.Text) ? "New agent" : NameBox.Text,
            agent_type = _selectedTemplate?.AgentType ?? "monitor_operative",
            config,
        };
    }
}
