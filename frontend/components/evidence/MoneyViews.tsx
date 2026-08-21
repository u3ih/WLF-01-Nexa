"use client";

import { FindingCard } from "@/components/Badges";
import { ui } from "@/lib/i18n";
import type { Finding, Lang } from "@/lib/types";

function Bar({ label, value, max, amount }: {
  label: string; value: number; max: number; amount: string;
}) {
  const pct = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0;
  return (
    <div className="bar-row">
      <span>{label}</span>
      <span className="bar"><span style={{ width: `${pct}%` }} /></span>
      <span className="mono">{amount}</span>
    </div>
  );
}

function Trend({ series, lang }: { series: any[]; lang: Lang }) {
  if (!series?.length) return null;
  const max = Math.max(...series.map((row) => row.spend_usd ?? 0), 1);
  const width = 100 / series.length;
  return (
    <div>
      <div className="stat-k" style={{ marginBottom: 6 }}>{ui(lang, "trend")}</div>
      <svg viewBox="0 0 100 34" preserveAspectRatio="none"
           style={{ width: "100%", height: 90 }}>
        {series.map((row, index) => {
          const height = ((row.spend_usd ?? 0) / max) * 30;
          return (
            <rect
              key={row.key}
              x={index * width + width * 0.18}
              y={32 - height}
              width={width * 0.64}
              height={Math.max(height, 0.4)}
              rx={0.6}
              fill="var(--accent)"
              opacity={index === series.length - 1 ? 1 : 0.55}
            />
          );
        })}
      </svg>
      <div style={{ display: "flex", justifyContent: "space-between",
                    color: "var(--text-faint)", fontSize: 10.5 }}>
        <span className="mono">{series[0].key}</span>
        <span className="mono">{series[series.length - 1].key}</span>
      </div>
    </div>
  );
}

export function CashflowView({ data, lang }: { data: any; lang: Lang }) {
  const max = Math.max(...data.categories.map((row: any) => row.total_usd));
  return (
    <>
      <div className="stat-grid" style={{ marginBottom: 12 }}>
        {[
          ["spend", data.totals.spend],
          ["fees", data.totals.fees],
          ["payin", data.totals.payin],
          ["payout", data.totals.payout],
          ["toCard", data.totals.transfer_to_card],
        ].map(([key, value]) => (
          <div className="stat" key={key as string}>
            <div className="stat-k">{ui(lang, key as never)}</div>
            <div className="stat-v">{value as string}</div>
          </div>
        ))}
      </div>
      {data.categories.map((row: any) => (
        <Bar
          key={row.category}
          label={row.label}
          value={row.total_usd}
          max={max}
          amount={row.total}
        />
      ))}
    </>
  );
}

export function ReportView({ data, lang }: { data: any; lang: Lang }) {
  return (
    <>
      <div className="stat-grid" style={{ marginBottom: 12 }}>
        <div className="stat">
          <div className="stat-k">{ui(lang, "spend")}</div>
          <div className="stat-v">{data.totals.spend}</div>
          <div className="stat-sub">
            {ui(lang, "vs")} {data.comparison.period_key}:{" "}
            {data.comparison.spend.delta}{" "}
            {data.comparison.spend.percent !== null
              ? `(${data.comparison.spend.percent}%)` : ""}
          </div>
        </div>
        <div className="stat">
          <div className="stat-k">{ui(lang, "fees")}</div>
          <div className="stat-v">{data.totals.fees}</div>
        </div>
        <div className="stat">
          <div className="stat-k">{ui(lang, "payin")}</div>
          <div className="stat-v">{data.totals.payin}</div>
        </div>
        <div className="stat">
          <div className="stat-k">{ui(lang, "payout")}</div>
          <div className="stat-v">{data.totals.payout}</div>
        </div>
      </div>
      <Trend series={data.trend} lang={lang} />
      <div className="stat-k" style={{ margin: "12px 0 4px" }}>
        {ui(lang, "top3")}
      </div>
      <table>
        <tbody>
          {data.top_purchases.map((row: any) => (
            <tr key={row.ref}>
              <td className="mono">{row.date}</td>
              <td>{row.merchant ?? row.descriptor}</td>
              <td className="num">{row.amount}</td>
              <td><span className="ref">{row.ref}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

export function SubscriptionsView({ data, lang }: { data: any; lang: Lang }) {
  return (
    <>
      <table>
        <thead>
          <tr>
            <th>Plan</th>
            <th className="num">Amount</th>
            <th>{ui(lang, "nextCharge")}</th>
            <th className="num">{ui(lang, "perYear")}</th>
            <th className="num">#</th>
          </tr>
        </thead>
        <tbody>
          {data.subscriptions.map((sub: any) => (
            <tr key={sub.merchant_key}>
              <td>
                {sub.merchant ?? sub.descriptor}
                <div style={{ color: "var(--text-faint)", fontSize: 11 }}
                     className="mono">{sub.descriptor}</div>
              </td>
              <td className="num">{sub.current_amount}</td>
              <td className="mono">{sub.next_charge}</td>
              <td className="num">{sub.annual_cost}</td>
              <td className="num">{sub.charge_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ marginTop: 12 }}>
        {(data.price_increases as Finding[]).map((finding) => (
          <FindingCard key={finding.id} finding={finding} lang={lang} />
        ))}
      </div>
    </>
  );
}
