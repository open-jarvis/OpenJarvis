using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using OpenJarvis.WinUI.Models;

namespace OpenJarvis.WinUI.Services;

public sealed class SseEvent
{
    public string? Event { get; init; }
    public string Data { get; init; } = "";
}

public sealed class JarvisApiClient
{
    private readonly HttpClient _http = new() { Timeout = Timeout.InfiniteTimeSpan };
    private string _base = "http://127.0.0.1:8000";

    public void SetBaseUrl(string url)
    {
        _base = url.TrimEnd('/');
    }

    public async Task<bool> IsHealthyAsync(CancellationToken cancellationToken)
    {
        try
        {
            using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            linked.CancelAfter(TimeSpan.FromSeconds(5));
            using var response = await _http.GetAsync($"{_base}/health", linked.Token);
            return response.IsSuccessStatusCode || (int)response.StatusCode == 503;
        }
        catch (HttpRequestException)
        {
            return false;
        }
        catch (TaskCanceledException)
        {
            return false;
        }
        catch (OperationCanceledException)
        {
            return false;
        }
    }

    public async Task<bool> IsEngineHealthyAsync(CancellationToken cancellationToken)
    {
        try
        {
            using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            linked.CancelAfter(TimeSpan.FromSeconds(5));
            using var response = await _http.GetAsync($"{_base}/health", linked.Token);
            return response.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }

    public async Task<ServerInfo?> GetInfoAsync(CancellationToken cancellationToken)
    {
        try
        {
            return await _http.GetFromJsonAsync<ServerInfo>($"{_base}/v1/info", cancellationToken);
        }
        catch
        {
            return null;
        }
    }

    public async Task<IReadOnlyList<string>> GetModelsAsync(CancellationToken cancellationToken)
    {
        try
        {
            using var response = await _http.GetAsync($"{_base}/v1/models", cancellationToken);
            response.EnsureSuccessStatusCode();
            using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync(cancellationToken));
            if (!doc.RootElement.TryGetProperty("data", out var data))
            {
                return [];
            }

            return data.EnumerateArray()
                .Select(item => item.TryGetProperty("id", out var id) ? id.GetString() ?? "" : "")
                .Where(id => !string.IsNullOrWhiteSpace(id))
                .ToList();
        }
        catch
        {
            return [];
        }
    }

    public async Task<IReadOnlyList<PendingApproval>> GetPendingApprovalsAsync(
        CancellationToken cancellationToken)
    {
        try
        {
            var payload = await _http.GetFromJsonAsync<JsonElement>(
                $"{_base}/v1/approvals/pending", cancellationToken);
            if (payload.ValueKind == JsonValueKind.Array)
            {
                return payload.Deserialize<List<PendingApproval>>() ?? [];
            }

            if (payload.TryGetProperty("approvals", out var approvals))
            {
                return approvals.Deserialize<List<PendingApproval>>() ?? [];
            }

            if (payload.TryGetProperty("pending", out var pending))
            {
                return pending.Deserialize<List<PendingApproval>>() ?? [];
            }
        }
        catch
        {
            // Backend may still be starting.
        }

        return [];
    }

    public async Task<TelemetryStats?> GetTelemetryStatsAsync(CancellationToken cancellationToken)
    {
        try
        {
            return await _http.GetFromJsonAsync<TelemetryStats>(
                $"{_base}/v1/telemetry/stats", cancellationToken);
        }
        catch
        {
            return null;
        }
    }

    public async Task<EnergyStats?> GetEnergyStatsAsync(CancellationToken cancellationToken)
    {
        try
        {
            return await _http.GetFromJsonAsync<EnergyStats>(
                $"{_base}/v1/telemetry/energy", cancellationToken);
        }
        catch
        {
            return null;
        }
    }

    public async Task<SavingsInfo?> GetSavingsAsync(CancellationToken cancellationToken)
    {
        try
        {
            return await _http.GetFromJsonAsync<SavingsInfo>($"{_base}/v1/savings", cancellationToken);
        }
        catch
        {
            return null;
        }
    }

    public async Task<IReadOnlyList<TraceSummary>> GetTracesAsync(
        int limit, CancellationToken cancellationToken)
    {
        try
        {
            var response = await _http.GetFromJsonAsync<TracesResponse>(
                $"{_base}/v1/traces?limit={limit}", cancellationToken);
            return response?.Traces ?? [];
        }
        catch
        {
            return [];
        }
    }

    public async Task<IReadOnlyList<ConnectorSummary>> GetConnectorsAsync(CancellationToken cancellationToken)
    {
        try
        {
            var payload = await _http.GetFromJsonAsync<JsonElement>(
                $"{_base}/v1/connectors", cancellationToken);
            if (payload.TryGetProperty("connectors", out var connectors))
            {
                return connectors.Deserialize<List<ConnectorSummary>>() ?? [];
            }
        }
        catch
        {
            // Backend may still be starting.
        }

        return [];
    }

    public async Task<ConnectorDetail?> GetConnectorDetailAsync(
        string connectorId, CancellationToken cancellationToken)
    {
        try
        {
            return await _http.GetFromJsonAsync<ConnectorDetail>(
                $"{_base}/v1/connectors/{connectorId}", cancellationToken);
        }
        catch
        {
            return null;
        }
    }

    /// <summary>Body shape depends on the connector's auth type: "filesystem"
    /// takes <c>{path}</c>, "token"/"credentials" take <c>{token}</c>,
    /// "local" and "oauth" take an empty body. Connector-specific extra
    /// fields some connectors need beyond that (e.g. weather's location,
    /// news_rss's feed URL) are out of scope for this generic form.</summary>
    public async Task<ConnectResult?> ConnectConnectorAsync(
        string connectorId, object body, CancellationToken cancellationToken)
    {
        try
        {
            using var response = await _http.PostAsJsonAsync(
                $"{_base}/v1/connectors/{connectorId}/connect", body, cancellationToken);
            return await response.Content.ReadFromJsonAsync<ConnectResult>(cancellationToken);
        }
        catch
        {
            return null;
        }
    }

    /// <summary>The backend 409s with "still stopping" during a disconnect
    /// race — null here means "didn't succeed this attempt", which the
    /// caller should treat as retryable, not a hard failure.</summary>
    public async Task<ConnectResult?> DisconnectConnectorAsync(
        string connectorId, CancellationToken cancellationToken)
    {
        try
        {
            using var response = await _http.PostAsJsonAsync(
                $"{_base}/v1/connectors/{connectorId}/disconnect", new { }, cancellationToken);
            if (!response.IsSuccessStatusCode)
            {
                return null;
            }

            return await response.Content.ReadFromJsonAsync<ConnectResult>(cancellationToken);
        }
        catch
        {
            return null;
        }
    }

    public async Task<bool> StartSyncAsync(string connectorId, CancellationToken cancellationToken)
    {
        try
        {
            using var response = await _http.PostAsJsonAsync(
                $"{_base}/v1/connectors/{connectorId}/sync", new { }, cancellationToken);
            return response.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }

    public async Task<SyncStatus?> GetSyncStatusAsync(string connectorId, CancellationToken cancellationToken)
    {
        try
        {
            return await _http.GetFromJsonAsync<SyncStatus>(
                $"{_base}/v1/connectors/{connectorId}/sync", cancellationToken);
        }
        catch
        {
            return null;
        }
    }

    public Task ApproveAsync(string id, CancellationToken cancellationToken) =>
        _http.PostAsync($"{_base}/v1/approvals/{id}/approve", null, cancellationToken);

    public Task DenyAsync(string id, CancellationToken cancellationToken) =>
        _http.PostAsync($"{_base}/v1/approvals/{id}/deny", null, cancellationToken);

    public IAsyncEnumerable<SseEvent> StreamChatAsync(
        object request, CancellationToken cancellationToken) =>
        StreamSseAsync(
            $"{_base}/v1/chat/completions",
            request,
            "Could not reach the OpenJarvis backend. Wait until status shows Ready, or open Setup if Foundry is missing.",
            "The chat request timed out while connecting to the backend.",
            "Chat",
            cancellationToken);

    /// <summary>The agent-chat endpoint is a queue, not a live stream: this
    /// posts one message (mode "queued" needs a scheduled/manual run to be
    /// processed; "immediate" triggers processing right away) and returns
    /// immediately with the created message (<c>status: "pending"</c>).
    /// Poll <see cref="GetAgentMessagesAsync"/> for the agent's reply —
    /// confirmed live: there is no SSE framing on this route at all,
    /// despite it superficially resembling the chat-completions endpoint.</summary>
    public async Task<AgentMessage?> PostAgentMessageAsync(
        string agentId, string content, string mode, CancellationToken cancellationToken)
    {
        try
        {
            using var response = await _http.PostAsJsonAsync(
                $"{_base}/v1/managed-agents/{agentId}/messages",
                new { content, mode },
                cancellationToken);
            return await response.Content.ReadFromJsonAsync<AgentMessage>(cancellationToken);
        }
        catch
        {
            return null;
        }
    }

    public async Task<IReadOnlyList<AgentMessage>> GetAgentMessagesAsync(
        string agentId, CancellationToken cancellationToken)
    {
        try
        {
            var payload = await _http.GetFromJsonAsync<JsonElement>(
                $"{_base}/v1/managed-agents/{agentId}/messages", cancellationToken);
            return payload.TryGetProperty("messages", out var messages)
                ? messages.Deserialize<List<AgentMessage>>() ?? []
                : [];
        }
        catch
        {
            return [];
        }
    }

    /// <summary>Shared SSE POST+parse loop behind <see cref="StreamChatAsync"/>
    /// and <see cref="StreamAgentMessageAsync"/> — same wire format
    /// (<c>event:</c>/<c>data:</c> lines, <c>[DONE]</c> sentinel) on both
    /// endpoints.</summary>
    private async IAsyncEnumerable<SseEvent> StreamSseAsync(
        string url,
        object request,
        string connectErrorMessage,
        string timeoutErrorMessage,
        string failureLabel,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken)
    {
        using var message = new HttpRequestMessage(HttpMethod.Post, url)
        {
            Content = JsonContent.Create(request)
        };
        message.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("text/event-stream"));

        HttpResponseMessage response;
        try
        {
            response = await _http.SendAsync(
                message, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        }
        catch (HttpRequestException ex)
        {
            throw new InvalidOperationException(connectErrorMessage, ex);
        }
        catch (TaskCanceledException ex) when (!cancellationToken.IsCancellationRequested)
        {
            throw new InvalidOperationException(timeoutErrorMessage, ex);
        }

        using (response)
        {
            if (!response.IsSuccessStatusCode)
            {
                var body = await response.Content.ReadAsStringAsync(cancellationToken);
                throw new InvalidOperationException($"{failureLabel} failed ({(int)response.StatusCode}): {body}");
            }

            await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken);
            using var reader = new StreamReader(stream, Encoding.UTF8);
            string? currentEvent = null;
            while (true)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var line = await reader.ReadLineAsync(cancellationToken);
                if (line is null)
                {
                    yield break;
                }

                if (line.StartsWith("event: ", StringComparison.Ordinal))
                {
                    currentEvent = line["event: ".Length..].Trim();
                }
                else if (line.StartsWith("data: ", StringComparison.Ordinal))
                {
                    var data = line["data: ".Length..];
                    if (data == "[DONE]")
                    {
                        yield break;
                    }

                    yield return new SseEvent { Event = currentEvent, Data = data };
                    currentEvent = null;
                }
                else if (string.IsNullOrWhiteSpace(line))
                {
                    currentEvent = null;
                }
            }
        }
    }

    public async Task<IReadOnlyList<ManagedAgentSummary>> GetManagedAgentsAsync(CancellationToken cancellationToken)
    {
        try
        {
            var payload = await _http.GetFromJsonAsync<JsonElement>(
                $"{_base}/v1/managed-agents", cancellationToken);
            return payload.TryGetProperty("agents", out var agents)
                ? agents.Deserialize<List<ManagedAgentSummary>>() ?? []
                : [];
        }
        catch
        {
            return [];
        }
    }

    public async Task<ManagedAgentSummary?> GetManagedAgentAsync(string id, CancellationToken cancellationToken)
    {
        try
        {
            return await _http.GetFromJsonAsync<ManagedAgentSummary>(
                $"{_base}/v1/managed-agents/{id}", cancellationToken);
        }
        catch
        {
            return null;
        }
    }

    public async Task<ManagedAgentSummary?> CreateManagedAgentAsync(object body, CancellationToken cancellationToken)
    {
        try
        {
            using var response = await _http.PostAsJsonAsync(
                $"{_base}/v1/managed-agents", body, cancellationToken);
            response.EnsureSuccessStatusCode();
            return await response.Content.ReadFromJsonAsync<ManagedAgentSummary>(cancellationToken);
        }
        catch
        {
            return null;
        }
    }

    public async Task<bool> DeleteManagedAgentAsync(string id, CancellationToken cancellationToken)
    {
        try
        {
            using var response = await _http.DeleteAsync($"{_base}/v1/managed-agents/{id}", cancellationToken);
            return response.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }

    private async Task<string?> PostLifecycleAsync(string id, string action, CancellationToken cancellationToken)
    {
        try
        {
            using var response = await _http.PostAsJsonAsync(
                $"{_base}/v1/managed-agents/{id}/{action}", new { }, cancellationToken);
            if (!response.IsSuccessStatusCode)
            {
                // 409 on /run (already running) is expected, not a failure to swallow silently.
                return (int)response.StatusCode == 409 ? "already_running" : null;
            }

            var doc = await response.Content.ReadFromJsonAsync<JsonElement>(cancellationToken);
            return doc.TryGetProperty("status", out var status) ? status.GetString() : "ok";
        }
        catch
        {
            return null;
        }
    }

    public Task<string?> PauseAgentAsync(string id, CancellationToken cancellationToken) =>
        PostLifecycleAsync(id, "pause", cancellationToken);

    public Task<string?> ResumeAgentAsync(string id, CancellationToken cancellationToken) =>
        PostLifecycleAsync(id, "resume", cancellationToken);

    public Task<string?> RunAgentAsync(string id, CancellationToken cancellationToken) =>
        PostLifecycleAsync(id, "run", cancellationToken);

    public Task<string?> RecoverAgentAsync(string id, CancellationToken cancellationToken) =>
        PostLifecycleAsync(id, "recover", cancellationToken);

    public async Task<IReadOnlyList<AgentTask>> GetAgentTasksAsync(string id, CancellationToken cancellationToken)
    {
        try
        {
            var payload = await _http.GetFromJsonAsync<JsonElement>(
                $"{_base}/v1/managed-agents/{id}/tasks", cancellationToken);
            return payload.TryGetProperty("tasks", out var tasks)
                ? tasks.Deserialize<List<AgentTask>>() ?? []
                : [];
        }
        catch
        {
            return [];
        }
    }

    public async Task<bool> CreateAgentTaskAsync(
        string id, string description, CancellationToken cancellationToken)
    {
        try
        {
            using var response = await _http.PostAsJsonAsync(
                $"{_base}/v1/managed-agents/{id}/tasks", new { description }, cancellationToken);
            return response.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }

    public async Task<IReadOnlyList<LearningLogEntry>> GetLearningLogAsync(
        string id, CancellationToken cancellationToken)
    {
        try
        {
            var payload = await _http.GetFromJsonAsync<JsonElement>(
                $"{_base}/v1/managed-agents/{id}/learning", cancellationToken);
            return payload.TryGetProperty("learning_log", out var log)
                ? log.Deserialize<List<LearningLogEntry>>() ?? []
                : [];
        }
        catch
        {
            return [];
        }
    }

    public Task RunLearningAsync(string id, CancellationToken cancellationToken) =>
        _http.PostAsync($"{_base}/v1/managed-agents/{id}/learning/run", null, cancellationToken);

    public async Task<IReadOnlyList<AgentTemplate>> GetAgentTemplatesAsync(CancellationToken cancellationToken)
    {
        try
        {
            var payload = await _http.GetFromJsonAsync<JsonElement>($"{_base}/v1/templates", cancellationToken);
            return payload.TryGetProperty("templates", out var templates)
                ? templates.Deserialize<List<AgentTemplate>>() ?? []
                : [];
        }
        catch
        {
            return [];
        }
    }

    public async Task<IReadOnlyList<ToolCatalogItem>> GetToolCatalogAsync(CancellationToken cancellationToken)
    {
        try
        {
            var payload = await _http.GetFromJsonAsync<JsonElement>($"{_base}/v1/tools", cancellationToken);
            return payload.TryGetProperty("tools", out var tools)
                ? tools.Deserialize<List<ToolCatalogItem>>() ?? []
                : [];
        }
        catch
        {
            return [];
        }
    }

    // ── Memory (/v1/memory/*) ───────────────────────────────────────

    public async Task<bool> StoreMemoryAsync(
        string content, object? metadata, CancellationToken cancellationToken)
    {
        try
        {
            using var response = await _http.PostAsJsonAsync(
                $"{_base}/v1/memory/store", new { content, metadata }, cancellationToken);
            return response.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }

    public async Task<IReadOnlyList<MemorySearchResult>> SearchMemoryAsync(
        string query, int topK, CancellationToken cancellationToken)
    {
        try
        {
            using var response = await _http.PostAsJsonAsync(
                $"{_base}/v1/memory/search", new { query, top_k = topK }, cancellationToken);
            var payload = await response.Content.ReadFromJsonAsync<JsonElement>(cancellationToken);
            return payload.TryGetProperty("results", out var results)
                ? results.Deserialize<List<MemorySearchResult>>() ?? []
                : [];
        }
        catch
        {
            return [];
        }
    }

    public async Task<MemoryStats?> GetMemoryStatsAsync(CancellationToken cancellationToken)
    {
        try
        {
            return await _http.GetFromJsonAsync<MemoryStats>($"{_base}/v1/memory/stats", cancellationToken);
        }
        catch
        {
            return null;
        }
    }

    /// <summary>Read-only — there is no matching write endpoint. Injection
    /// settings are saved via <c>TomlSettings</c> into config.toml instead
    /// and need a backend restart to take effect.</summary>
    public async Task<MemoryConfigInfo?> GetMemoryConfigAsync(CancellationToken cancellationToken)
    {
        try
        {
            return await _http.GetFromJsonAsync<MemoryConfigInfo>($"{_base}/v1/memory/config", cancellationToken);
        }
        catch
        {
            return null;
        }
    }

    public async Task<MemoryIndexResult?> IndexMemoryPathAsync(string path, CancellationToken cancellationToken)
    {
        try
        {
            using var response = await _http.PostAsJsonAsync(
                $"{_base}/v1/memory/index", new { path }, cancellationToken);
            return await response.Content.ReadFromJsonAsync<MemoryIndexResult>(cancellationToken);
        }
        catch
        {
            return null;
        }
    }

    // ── Deep Research (/api/research) ───────────────────────────────

    /// <summary>SSE frames have no <c>event:</c> line and no <c>[DONE]</c>
    /// sentinel — just a terminal <c>{"type":"done"}</c> JSON frame followed
    /// by the stream closing. <see cref="StreamSseAsync"/> already tolerates
    /// that shape; callers switch on each frame's <c>Data</c> JSON "type".</summary>
    public IAsyncEnumerable<SseEvent> StreamResearchAsync(
        object request, CancellationToken cancellationToken) =>
        StreamSseAsync(
            $"{_base}/api/research",
            request,
            "Could not reach the OpenJarvis backend for Deep Research.",
            "The research request timed out while connecting to the backend.",
            "Research",
            cancellationToken);

    // ── Messaging channels (/v1/managed-agents/{id}/channels, /v1/channels/sendblue/*) ──

    public async Task<IReadOnlyList<ChannelBinding>> GetChannelBindingsAsync(
        string agentId, CancellationToken cancellationToken)
    {
        try
        {
            var payload = await _http.GetFromJsonAsync<JsonElement>(
                $"{_base}/v1/managed-agents/{agentId}/channels", cancellationToken);
            return payload.TryGetProperty("bindings", out var bindings)
                ? bindings.Deserialize<List<ChannelBinding>>() ?? []
                : [];
        }
        catch
        {
            return [];
        }
    }

    public async Task<ChannelBinding?> BindChannelAsync(
        string agentId, string channelType, object? config, string routingMode,
        CancellationToken cancellationToken)
    {
        try
        {
            using var response = await _http.PostAsJsonAsync(
                $"{_base}/v1/managed-agents/{agentId}/channels",
                new { channel_type = channelType, config, routing_mode = routingMode },
                cancellationToken);
            if (!response.IsSuccessStatusCode)
            {
                return null;
            }

            return await response.Content.ReadFromJsonAsync<ChannelBinding>(cancellationToken);
        }
        catch
        {
            return null;
        }
    }

    public async Task<bool> UnbindChannelAsync(
        string agentId, string bindingId, CancellationToken cancellationToken)
    {
        try
        {
            using var response = await _http.DeleteAsync(
                $"{_base}/v1/managed-agents/{agentId}/channels/{bindingId}", cancellationToken);
            return response.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }

    public async Task<SendBlueVerifyResult?> VerifySendBlueAsync(
        string apiKeyId, string apiSecretKey, CancellationToken cancellationToken)
    {
        try
        {
            using var response = await _http.PostAsJsonAsync(
                $"{_base}/v1/channels/sendblue/verify",
                new { api_key_id = apiKeyId, api_secret_key = apiSecretKey },
                cancellationToken);
            if (!response.IsSuccessStatusCode)
            {
                return null;
            }

            return await response.Content.ReadFromJsonAsync<SendBlueVerifyResult>(cancellationToken);
        }
        catch
        {
            return null;
        }
    }

    public async Task<bool> RegisterSendBlueWebhookAsync(
        string apiKeyId, string apiSecretKey, string webhookUrl, CancellationToken cancellationToken)
    {
        try
        {
            using var response = await _http.PostAsJsonAsync(
                $"{_base}/v1/channels/sendblue/register-webhook",
                new { api_key_id = apiKeyId, api_secret_key = apiSecretKey, webhook_url = webhookUrl },
                cancellationToken);
            return response.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }

    // ── Tool/channel credentials (/v1/tools/{tool}/credentials) ─────
    // Separate mechanism from cloud-keys.env: these persist to
    // credentials.toml via core/credentials.py's save_credential(), take
    // effect immediately (no restart), and cover Tavily plus every
    // non-live messaging channel (Telegram, Discord, email, etc.).

    public async Task<IReadOnlyList<string>> SaveToolCredentialsAsync(
        string toolName, IDictionary<string, string> keys, CancellationToken cancellationToken)
    {
        try
        {
            using var response = await _http.PostAsJsonAsync(
                $"{_base}/v1/tools/{toolName}/credentials", keys, cancellationToken);
            var payload = await response.Content.ReadFromJsonAsync<JsonElement>(cancellationToken);
            return payload.TryGetProperty("saved", out var saved)
                ? saved.Deserialize<List<string>>() ?? []
                : [];
        }
        catch
        {
            return [];
        }
    }

    public async Task<bool> DeleteToolCredentialAsync(
        string toolName, string key, CancellationToken cancellationToken)
    {
        try
        {
            using var response = await _http.DeleteAsync(
                $"{_base}/v1/tools/{toolName}/credentials/{key}", cancellationToken);
            return response.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }

    public async Task<Dictionary<string, bool>> GetToolCredentialStatusAsync(
        string toolName, CancellationToken cancellationToken)
    {
        try
        {
            return await _http.GetFromJsonAsync<Dictionary<string, bool>>(
                $"{_base}/v1/tools/{toolName}/credentials/status", cancellationToken) ?? [];
        }
        catch
        {
            return [];
        }
    }

    // ── Cloud API keys (/v1/cloud/reload) ────────────────────────────
    // Sets os.environ in the running server process immediately; does not
    // itself touch cloud-keys.env — the caller persists that file via
    // CloudKeysStore separately for the setting to survive a restart.

    public async Task<CloudReloadResult?> ReloadCloudKeysAsync(
        IDictionary<string, string> keys, CancellationToken cancellationToken)
    {
        try
        {
            using var response = await _http.PostAsJsonAsync(
                $"{_base}/v1/cloud/reload", new { keys }, cancellationToken);
            return await response.Content.ReadFromJsonAsync<CloudReloadResult>(cancellationToken);
        }
        catch
        {
            return null;
        }
    }
}
