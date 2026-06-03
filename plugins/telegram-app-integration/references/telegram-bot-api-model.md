# Telegram Bot API Model

This reference explains the runtime shape an application must own when it integrates Telegram Bot API.

## Runtime Ownership

Telegram integration belongs to the target application. The app decides whether it exposes an HTTP webhook, runs a polling worker, or supports both. Codex and this plugin are not message receivers and do not operate the bot.

## Webhook vs Polling

Use webhook when the app has a stable public HTTPS endpoint, production traffic should be push-based, and the deployment platform supports inbound requests.

Use polling when the app is in development, has no public endpoint, runs an internal worker, or needs controlled pull-based processing.

Support both only when the same normalized event contract is shared by both paths. Do not let webhook and polling drift into separate behavior.

## Update Types To Model

The app should treat these Telegram fields as untrusted input:

- message text and entities;
- commands;
- callback query data;
- chat, user, and group metadata;
- captions;
- file metadata;
- edited messages and replies.

## Inbound Verification

Webhook integrations need app-owned verification for the inbound request, usually through a webhook secret or equivalent platform control. Polling integrations need app-owned update offset handling, replay handling, and rate controls.

The Bot API token is app-owned protected material. This plugin may name the required source, but it must not include token values or commands that provision Telegram resources.

In both modes, normalize the Telegram update before calling app handlers. Handlers should receive an internal event type, not the raw remote payload as their primary contract.
