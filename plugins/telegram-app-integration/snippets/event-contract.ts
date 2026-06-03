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
    allowed: boolean;
  };
  actor?: {
    id: string;
    allowed: boolean;
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
  policy: {
    allowed: boolean;
    reason: string;
  };
}
