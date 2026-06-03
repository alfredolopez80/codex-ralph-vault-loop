// Illustrative only. This is a contract sketch, not a runtime package.

export interface TelegramOutboundDraft {
  chatId: string;
  text: string;
  parseMode?: "plain" | "markdown" | "html";
}

export interface TelegramOutboundDecision {
  allowed: boolean;
  reason: string;
  safeText?: string;
}

export function decideTelegramTextSend(
  draft: TelegramOutboundDraft,
  hasRedContent: (text: string) => boolean,
): TelegramOutboundDecision {
  if (draft.text.length > 4096) {
    return { allowed: false, reason: "message_too_long" };
  }

  if (hasRedContent(draft.text)) {
    return { allowed: false, reason: "red_content_blocked" };
  }

  return {
    allowed: true,
    reason: "ok",
    safeText:
      draft.parseMode && draft.parseMode !== "plain"
        ? escapeFormattedText(draft.text)
        : draft.text,
  };
}

function escapeFormattedText(text: string): string {
  return text.replace(/[<>&*_`[\]()]/g, "\\$&");
}
