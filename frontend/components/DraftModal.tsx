"use client";

import { useState } from "react";

import { api } from "@/lib/api";
import { ui } from "@/lib/i18n";
import type { Lang } from "@/lib/types";

/** Draft -> confirm -> send. The recipient field is fixed to the account owner
 *  and is not editable, because the backend refuses any other address. */
export function DraftModal({
  lang, draft, onClose,
}: {
  lang: Lang;
  draft: any;
  onClose: () => void;
}) {
  const [sent, setSent] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirmSend() {
    setBusy(true);
    setError(null);
    try {
      setSent(await api.sendReport(draft.confirm_token, lang));
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : String(exception));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        <div className="card-head">
          <span className="card-title">{ui(lang, "draftTitle")}</span>
          <span className="badge badge-confirm">{draft.period_label}</span>
        </div>
        <div className="card-body">
          <dl className="kv" style={{ marginBottom: 10 }}>
            <dt>{ui(lang, "draftTo")}</dt>
            <dd className="mono">{draft.recipient}</dd>
            <dt>Subject</dt>
            <dd>{draft.subject}</dd>
          </dl>
          <p style={{ color: "var(--label-confirm)", fontSize: 12.5 }}>
            {draft.confirm_prompt}
          </p>
          <pre>{draft.body ?? draft.body_preview}</pre>
          {error ? <p className="err">{error}</p> : null}
          {sent ? (
            <p className="chip" style={{ marginTop: 8 }}>
              <span className="k">{ui(lang, "sent")}</span>
              <span className="v mono">{sent.recipient}</span>
              <span className="k">{sent.delivery}</span>
            </p>
          ) : null}
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button
              className="btn btn-primary"
              onClick={confirmSend}
              disabled={busy || Boolean(sent)}
            >
              {busy ? ui(lang, "sending") : ui(lang, "confirmSend")}
            </button>
            <button className="btn btn-ghost" onClick={onClose}>
              {ui(lang, "cancel")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
