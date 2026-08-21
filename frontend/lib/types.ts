export type Lang = "vi" | "en";

export interface Source {
  kind: string;
  kind_text: string;
  ref: string;
  detail: string;
}

export interface Dispute {
  statement_date: string | null;
  dispute_deadline: string | null;
  days_left: number | null;
  window_days: number;
  expired: boolean;
  text: string;
}

export interface Finding {
  id: string;
  kind: string;
  label: "recurring_confirmed" | "needs_your_confirmation" | "insufficient_data";
  label_text: string;
  title: string;
  detail: string;
  next_step: string;
  amount: string;
  amount_usd: number;
  confidence: number;
  occurred_on: string | null;
  txn_ids: string[];
  sources: Source[];
  dispute: Dispute;
}

export interface ChatReply {
  answer: string;
  tool: string | null;
  tools_used: string[];
  routed_by?: string;
  source: string;
  refused: boolean;
  lang: Lang;
  disclaimer: string;
  labels: Record<string, string>;
  guardrail: {
    blocked: boolean;
    intent: string | null;
    severity: string | null;
    guidance_request: boolean;
  };
  llm: { mode: string; model: string; available: boolean; detail: string };
  fx: { vnd_rate: number; vnd_enabled: boolean; note: string };
  checks?: { violations?: string[]; ungrounded_numbers?: string[] };
  data?: any;
}

export interface Summary {
  account: {
    owner_name: string;
    owner_email: string;
    account_masked: string;
    card_masked: string;
    card_last4: string;
    statement_date: string;
    period_start: string;
    currency: string;
  };
  counts: Record<string, number>;
  labels: Record<string, number>;
  email_recon: Record<string, number>;
  cashflow: Record<string, any>;
  wallet: Record<string, any>;
  sources: Record<string, string>;
  statement_date: string;
  findings: Finding[];
  disclaimer: string;
  fx: { vnd_rate: number; vnd_enabled: boolean; note: string };
}
export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
}

export interface ChatConversation {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
}
