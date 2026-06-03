// Illustrative only. Adapt this shape inside the target app before use.

export type TelegramIngressSource = "webhook" | "polling";

export type TelegramEventKind =
  | "command"
  | "text"
  | "callback"
  | "edited"
  | "unsupported";

export interface TelegramAppEvent {
  eventId: string;
  source: TelegramIngressSource;
  updateId: number;
  kind: TelegramEventKind;
  chat: {
    id: string;
    type: "private" | "group" | "supergroup" | "channel";
  };
  actor?: {
    id: string;
  };
  command?: {
    name: string;
    args: readonly string[];
  };
  callback?: {
    name: string;
    scope: string;
  };
  text?: string;
  policy: TelegramAccessPolicyDecision;
}

export type TelegramAccessPolicyDecision =
  | {
      allowed: true;
      reason: "allowed_dm" | "allowed_group_mention" | "allowed_explicit_route";
      subjects: {
        chat: "allowed";
        actor?: "allowed";
      };
    }
  | {
      allowed: false;
      reason:
        | "chat_not_allowed"
        | "actor_not_allowed"
        | "group_disabled"
        | "mention_required"
        | "rate_limited";
      subjects: {
        chat?: "blocked" | "unknown";
        actor?: "blocked" | "unknown";
      };
    };
