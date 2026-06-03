// Illustrative only. This checks destination and text safety, not the full
// outbound policy. Target apps must wrap it with rate limits, audit writes,
// and exception-safe reply handling.

export interface TelegramOutboundDraft {
  chatId: string;
  authorizedChatId: string;
  text: string;
  parseMode?: "plain" | "markdown-v2" | "html";
}

export interface TelegramOutboundDecision {
  allowed: boolean;
  reason: string;
  safeText?: string;
}

export function decideTelegramTextContentSafety(
  draft: TelegramOutboundDraft,
  hasRedContent: (text: string) => boolean,
): TelegramOutboundDecision {
  if (draft.chatId !== draft.authorizedChatId) {
    return { allowed: false, reason: "chat_not_authorized" };
  }

  if (draft.text.length > 4096) {
    return { allowed: false, reason: "message_too_long" };
  }

  if (hasRedContent(draft.text)) {
    return { allowed: false, reason: "red_content_blocked" };
  }

  return {
    allowed: true,
    reason: "ok",
    safeText: formatSafeText(draft.text, draft.parseMode ?? "plain"),
  };
}

function formatSafeText(
  text: string,
  parseMode: "plain" | "markdown-v2" | "html",
): string {
  if (parseMode === "html") {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  if (parseMode === "markdown-v2") {
    return text.replace(/[_*[\]()~`>#+\-=|{}.!\\]/g, "\\$&");
  }

  return text;
}
