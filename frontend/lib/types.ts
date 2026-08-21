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
    /** Cards on the account. Identified by code and nickname — a statement
     *  that carries no PAN leaves `masked` null rather than inventing digits. */
    cards?: Array<{
      code: string;
      card_id?: string;
      name: string;
      currency: string;
      status: string;
      network?: string;
      expiry?: string;
      masked: string | null;
      balance_cents?: number | null;
      total_deposit_cents?: number | null;
      total_withdrawal_cents?: number | null;
    }>;
    /** Receiving accounts. `has_ledger` is false when the export carries only
     *  a total for them and no itemised rows. */
    virtual_accounts?: Array<{
      masked: string;
      label: string;
      payout_source: string;
      bank_name: string;
      currency: string;
      status: string;
      total_received_cents: number | null;
      has_ledger: boolean;
    }>;
    statement_date: string;
    period_start: string;
    currency: string;
    /** Every currency the statement holds. Totals are never summed across them. */
    currencies?: string[];
  };
  counts: Record<string, number>;
  labels: Record<string, number>;
  email_recon: Record<string, number>;
  cashflow: Record<string, any>;
  wallet: Record<string, any>;
  sources: Record<string, string>;
  /** What the loader had to decide about the input: a file skipped, a ledger
   *  the export did not include, a column that held a placeholder. */
  input_notes?: string[];
  mailbox?: string;
  mailboxes?: Record<string, number>;
  statement_date: string;
  findings: Finding[];
  disclaimer: string;
  fx: { vnd_rate: number; vnd_enabled: boolean; note: string };
}
