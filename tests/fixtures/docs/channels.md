# Channel Integrations

OpenJarvis ships adapters for many messaging platforms.

## Telegram

Set `TELEGRAM_BOT_TOKEN` in your env and call `TelegramChannel().connect()`. Incoming messages are delivered via the `on_message` callback.

## Slack

Install the `channel-slack` extra and provide a bot token starting with `xoxb-`. Slack uses socket mode by default but HTTP event mode is also supported.

## Discord

Discord needs a bot token and intents configured for message content. Add the bot to your server first, then register the channel.

## Adding a New Channel

Create a subclass of `BaseChannel` in `src/openjarvis/channels/your_channel.py`. Decorate with `@ChannelRegistry.register("name")`. Implement `connect`, `disconnect`, `send`, `status`, `list_channels`, and `on_message`.
