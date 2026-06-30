// ARC Macro 2.0 — REPORT: Executive Briefing
// A plain-language summary that consolidates analysis, suggestions, positions, trades, and results.
// The operator opens this page and immediately understands what the system is saying and what to do.
import type { MacroContext, Sleeve, WebState } from "@shared/autonomy";
import { useAutonomyState } from "../useAutonomy";
import { Panel, Tag, Pos, Dot } from "../components";

// ---- Helpers ----------------------------------------------------------------

function pct(v: number | null | undefined, digits = 1): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

function signed(v: number | null | undefined, digits = 3): string {
  if (v == null || Number.isNaN(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}`;
}

function directionLabel(pos: number, instrument: string): string {
  if (pos === 0) return "Flat (sem posição)";
  if (instrument.includes("DI")) {
    return pos > 0 ? "APLICADO (receive fixed / long DI)" : "TOMADO (pay fixed / short DI)";
  }
  return pos > 0 ? "COMPRADO USD (long USDBRL)" : "VENDIDO USD (short USDBRL)";
}

function tradeInstruction(sleeve: Sleeve): string {
  const p = sleeve.proposal;
  if (!p) return "Sem proposta ativa.";
  if (p.circuit_halted) return "HALTED — sem execução. Circuit breaker ativo.";
  if (p.sized_exposure === 0) return "Sem execução (posição zero).";

  const pos = p.proposed_position;
  const exp = p.sized_exposure;

  // sized_exposure is the fraction of AUM allocated as notional
  // DI contract notional ≈ R$100,000; WDO mini-contract = USD 10,000 ≈ R$57,000
  const AUM = 10_000_000; // R$ 10MM default

  if (sleeve.instrument_label.includes("DI Front")) {
    const contracts = Math.round(exp * AUM / 100_000);
    return pos > 0
      ? `Comprar ~${contracts} contratos DI1F27 (receive fixed 1Y)`
      : `Vender ~${contracts} contratos DI1F27 (pay fixed 1Y)`;
  }
  if (sleeve.instrument_label.includes("DI Long")) {
    const contracts = Math.round(exp * AUM / 100_000);
    return pos < 0
      ? `Vender ~${contracts} contratos DI1F31 (pay fixed 5Y)`
      : `Comprar ~${contracts} contratos DI1F31 (receive fixed 5Y)`;
  }
  if (sleeve.instrument_label.includes("FX") || sleeve.instrument_label.includes("USD")) {
    const contracts = Math.round(exp * AUM / 57_000);
    return pos > 0
      ? `Comprar ~${contracts} mini-contratos WDO (long USD)`
      : `Vender ~${contracts} mini-contratos WDO (short USD)`;
  }
  return `Sized exposure: ${pct(exp)}`;
}

function regimeNarrative(macro: MacroContext | null): string {
  if (!macro?.regime?.latest) return "Regime indisponível.";
  const probs = macro.regime.latest;
  const sorted = Object.entries(probs)
    .filter(([_, v]) => !Number.isNaN(v) && v != null)
    .sort((a, b) => b[1] - a[1]);
  if (sorted.length === 0) return "Regime indisponível.";
  const dominant = sorted[0];
  const second = sorted.length > 1 ? sorted[1] : null;

  const labels: Record<string, string> = {
    carry: "Carry — juros altos com vol controlada, ambiente favorável a posições de taxa",
    P_carry: "Carry — juros altos com vol controlada, ambiente favorável a posições de taxa",
    riskoff: "Risk-Off — aversão a risco global, USD forte, pressão em emergentes",
    P_riskoff: "Risk-Off — aversão a risco global, USD forte, pressão em emergentes",
    stress: "Stress — crise/pânico, correlações quebram, vol explode",
    P_stress: "Stress — crise/pânico, correlações quebram, vol explode",
    domestic_calm: "Calma Doméstica — Brasil tranquilo, sem ruído político/fiscal",
    P_domestic_calm: "Calma Doméstica — Brasil tranquilo, sem ruído político/fiscal",
    domestic_stress: "Stress Doméstico — pressão fiscal ou política interna",
    P_domestic_stress: "Stress Doméstico — pressão fiscal ou política interna",
  };

  const domLabel = labels[dominant[0]] || dominant[0];
  const secLabel = second ? (labels[second[0]] || second[0]) : "—";

  return `Regime dominante: ${domLabel} (${(dominant[1] * 100).toFixed(0)}%).` +
    (second ? ` Segundo: ${secLabel} (${(second[1] * 100).toFixed(0)}%).` : "");
}

function macroNarrative(macro: MacroContext | null): string {
  if (!macro) return "Dados macro indisponíveis — Python bridge offline.";
  const parts: string[] = [];

  if (macro.rstar) {
    parts.push(`Taxa neutra real (r*) estimada em ${macro.rstar.latest.toFixed(2)}% — `
      + `${macro.rstar.history.length > 1 ? (macro.rstar.history[macro.rstar.history.length - 1][1] > macro.rstar.history[macro.rstar.history.length - 2][1] ? "tendência de alta" : "tendência de queda") : "sem histórico suficiente"}.`);
  }

  if (macro.state_vars) {
    const policyGap = macro.state_vars.find(v => v.key === "Z_policy_gap" || v.label.includes("policy"));
    const realDiff = macro.state_vars.find(v => v.key === "Z_real_rate_diff" || v.label.includes("real rate"));
    const fiscal = macro.state_vars.find(v => v.key === "Z_fiscal" || v.label.includes("fiscal"));
    const cds = macro.state_vars.find(v => v.key === "Z_cds" || v.label.includes("CDS"));

    if (policyGap && policyGap.value > 0.5) {
      parts.push(`Policy gap em +${policyGap.value.toFixed(2)}σ — Selic acima do neutro, há espaço para corte.`);
    }
    if (realDiff && realDiff.value > 1.0) {
      parts.push(`Diferencial de juros reais BR-US em +${realDiff.value.toFixed(2)}σ — muito atrativo para carry.`);
    }
    if (fiscal && fiscal.value > 0.5) {
      parts.push(`Stress fiscal em +${fiscal.value.toFixed(2)}σ — pressão moderada nas contas públicas.`);
    }
    if (cds && cds.value < -1.0) {
      parts.push(`CDS Brasil 5Y em ${cds.value.toFixed(2)}σ — risco-país comprimido (positivo).`);
    }
  }

  if (macro.fx_fair) {
    const mis = macro.fx_fair.misalignment_pct;
    if (mis != null) {
      parts.push(mis > 0
        ? `BRL ${mis.toFixed(1)}% barato vs. fair value (${macro.fx_fair.fair?.toFixed(3)} vs spot ${macro.fx_fair.spot?.toFixed(3)}).`
        : `BRL ${Math.abs(mis).toFixed(1)}% caro vs. fair value.`);
    }
  }

  return parts.length > 0 ? parts.join(" ") : "Contexto macro disponível — sem alertas significativos.";
}

function portfolioNarrative(sleeves: Sleeve[]): string {
  const operating = sleeves.filter(s => s.proposal?.action_suggestion === "OPERATE" && !s.proposal?.circuit_halted);
  if (operating.length === 0) return "Nenhum sleeve operando — portfólio flat.";

  const diShort = operating.find(s => s.instrument_label.includes("DI") && (s.proposal?.proposed_position ?? 0) < 0);
  const diLong = operating.find(s => s.instrument_label.includes("DI") && (s.proposal?.proposed_position ?? 0) > 0);

  if (diShort && diLong) {
    return "Portfólio líquido é um STEEPENER — aplicado na ponta curta (juros caem) e tomado na ponta longa (juros sobem). " +
      "Aposta que a curva DI vai inclinar. Ganha se: cortes de Selic + prêmio fiscal na parte longa.";
  }
  if (diLong && !diShort) {
    return "Portfólio é RECEIVER puro — apostando em queda generalizada de juros.";
  }
  if (diShort && !diLong) {
    return "Portfólio é PAYER puro — apostando em alta generalizada de juros.";
  }
  return "Portfólio misto — verifique posições individuais.";
}

function suggestionForSleeve(sleeve: Sleeve): string {
  const p = sleeve.proposal;
  if (!p) return "Sem proposta.";

  if (p.circuit_halted) {
    return `⛔ NÃO OPERAR. Circuit breaker ativo: ${p.circuit_reasons.join("; ")}. Aguardar normalização.`;
  }

  if (p.drift_warnings.length > 0) {
    return `⚠️ ATENÇÃO: ${p.drift_warnings.join("; ")}. O modelo divergiu do frozen — considere SKIP se drift > 20%.`;
  }

  if (p.action_suggestion === "OPERATE") {
    const strength = Math.abs(p.proposed_position);
    if (strength > 1.0) return `✅ SINAL FORTE (${signed(p.proposed_position)}). Modelo convicto — APPROVE recomendado.`;
    if (strength > 0.3) return `✅ Sinal moderado (${signed(p.proposed_position)}). APPROVE razoável.`;
    return `⚡ Sinal fraco (${signed(p.proposed_position)}). Considere SKIP se não há convicção qualitativa.`;
  }

  return `Modelo sugere ${p.action_suggestion}.`;
}

// ---- Main Component ---------------------------------------------------------

export function Report() {
  const { data, isLoading, error } = useAutonomyState();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center" style={{ minHeight: 300 }}>
        <span className="mesa-label">Carregando report...</span>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex items-center justify-center" style={{ minHeight: 300 }}>
        <span className="mesa-neg">Erro ao carregar dados do sistema.</span>
      </div>
    );
  }

  const { meta, sleeves, pool, macro } = data as WebState;
  const month = sleeves[0]?.proposal?.month ?? "—";
  const operating = sleeves.filter(s => s.proposal?.action_suggestion === "OPERATE");
  const halted = sleeves.filter(s => s.proposal?.circuit_halted);

  return (
    <div className="flex flex-col gap-4" style={{ maxWidth: 900 }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="mesa-h" style={{ fontSize: 16, letterSpacing: "0.12em", margin: 0 }}>
            EXECUTIVE BRIEFING
          </h1>
          <span className="mesa-label">Mês de referência: {month} · Data: {meta.as_of ?? "—"}</span>
        </div>
        <div className="flex items-center gap-2">
          <Dot kind={operating.length > 0 ? "live" : "idle"} />
          <span className="mesa-label">{operating.length} operando · {halted.length} halted</span>
        </div>
      </div>

      {/* 1. Visão Geral */}
      <Panel title="1 · VISÃO GERAL — O QUE O SISTEMA ESTÁ DIZENDO">
        <div style={{ padding: "12px 14px" }}>
          <p className="mesa-h" style={{ fontSize: 13, lineHeight: 1.7, margin: "0 0 12px" }}>
            {portfolioNarrative(sleeves)}
          </p>
          <p style={{ fontSize: 12, lineHeight: 1.7, margin: 0, color: "var(--txt)" }}>
            {regimeNarrative(macro)}
          </p>
        </div>
      </Panel>

      {/* 2. Contexto Macro */}
      <Panel title="2 · CONTEXTO MACRO — POR QUE ESSAS POSIÇÕES">
        <div style={{ padding: "12px 14px" }}>
          <p style={{ fontSize: 12, lineHeight: 1.8, margin: 0, color: "var(--txt)" }}>
            {macroNarrative(macro)}
          </p>
          {macro?.di_curve && macro.di_curve.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <span className="mesa-label">Curva DI nominal</span>
              <div className="flex gap-3 flex-wrap" style={{ marginTop: 6 }}>
                {macro.di_curve.map(p => (
                  <div key={p.tenor} className="flex flex-col items-center">
                    <span className="mesa-num mesa-h" style={{ fontSize: 13 }}>{p.rate.toFixed(2)}</span>
                    <span className="mesa-label" style={{ fontSize: 9 }}>{p.tenor}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </Panel>

      {/* 3. Posições e Trades */}
      <Panel title="3 · POSIÇÕES E TRADES — O QUE EXECUTAR">
        <div style={{ padding: 0 }}>
          <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
            <thead>
              <tr className="mesa-row" style={{ background: "var(--panel-2)" }}>
                <th style={{ padding: "8px 12px", textAlign: "left" }} className="mesa-label">Sleeve</th>
                <th style={{ padding: "8px 12px", textAlign: "left" }} className="mesa-label">Direção</th>
                <th style={{ padding: "8px 12px", textAlign: "right" }} className="mesa-label">Posição</th>
                <th style={{ padding: "8px 12px", textAlign: "right" }} className="mesa-label">Exposure</th>
                <th style={{ padding: "8px 12px", textAlign: "left" }} className="mesa-label">Trade (AUM R$10MM)</th>
              </tr>
            </thead>
            <tbody>
              {sleeves.map(s => {
                const p = s.proposal;
                const pos = p?.proposed_position ?? 0;
                return (
                  <tr key={s.name} className="mesa-row mesa-rowhover">
                    <td style={{ padding: "10px 12px" }}>
                      <div className="mesa-h" style={{ fontSize: 12 }}>{s.name}</div>
                      <div className="mesa-label" style={{ fontSize: 9 }}>{s.instrument_label}</div>
                    </td>
                    <td style={{ padding: "10px 12px", fontSize: 11 }}>
                      <span className={pos > 0 ? "mesa-pos" : pos < 0 ? "mesa-neg" : "mesa-dim"}>
                        {directionLabel(pos, s.instrument_label)}
                      </span>
                    </td>
                    <td style={{ padding: "10px 12px", textAlign: "right" }}>
                      <Pos value={pos} />
                    </td>
                    <td style={{ padding: "10px 12px", textAlign: "right" }}>
                      <span className="mesa-num">{pct(p?.sized_exposure)}</span>
                    </td>
                    <td style={{ padding: "10px 12px", fontSize: 11 }}>
                      <span className={p?.circuit_halted ? "mesa-neg" : "mesa-h"}>
                        {tradeInstruction(s)}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div style={{ padding: "8px 12px", borderTop: "1px solid var(--line)" }}>
            <span className="mesa-label" style={{ fontSize: 9 }}>
              Contratos calculados para AUM = R$ 10MM. Ajuste proporcionalmente ao seu capital.
              DV01 estimados: DI1F27 ≈ R$9.50/bp, DI1F31 ≈ R$42/bp, WDO = USD 10k/contrato.
            </span>
          </div>
        </div>
      </Panel>

      {/* 4. Sugestões do Sistema */}
      <Panel title="4 · SUGESTÕES — APPROVE, SKIP OU OVERRIDE?">
        <div style={{ padding: "12px 14px" }}>
          {sleeves.map(s => (
            <div key={s.name} className="mesa-row" style={{ padding: "10px 0", borderColor: "var(--line)" }}>
              <div className="flex items-center gap-2" style={{ marginBottom: 4 }}>
                <span className="mesa-h" style={{ fontSize: 12 }}>{s.name}</span>
                <Tag kind={s.proposal?.action_suggestion === "OPERATE" ? "operate" : s.proposal?.circuit_halted ? "halt" : "warmup"}>
                  {s.proposal?.action_suggestion ?? "—"}
                </Tag>
                {s.last_operator_decision && (
                  <span className="mesa-label" style={{ fontSize: 9 }}>
                    (última decisão: {s.last_operator_decision.action} em {s.last_operator_decision.month})
                  </span>
                )}
              </div>
              <p style={{ fontSize: 12, margin: 0, lineHeight: 1.6, color: "var(--txt)" }}>
                {suggestionForSleeve(s)}
              </p>
            </div>
          ))}
        </div>
      </Panel>

      {/* 5. Resultados Operacionais */}
      <Panel title="5 · RESULTADOS — PERFORMANCE OPERACIONAL (PRE-VERDICT)">
        <div style={{ padding: 0 }}>
          <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
            <thead>
              <tr className="mesa-row" style={{ background: "var(--panel-2)" }}>
                <th style={{ padding: "8px 12px", textAlign: "left" }} className="mesa-label">Sleeve</th>
                <th style={{ padding: "8px 12px", textAlign: "center" }} className="mesa-label">Meses</th>
                <th style={{ padding: "8px 12px", textAlign: "right" }} className="mesa-label">Retorno (frozen)</th>
                <th style={{ padding: "8px 12px", textAlign: "right" }} className="mesa-label">Retorno (operator)</th>
                <th style={{ padding: "8px 12px", textAlign: "right" }} className="mesa-label">Max DD</th>
                <th style={{ padding: "8px 12px", textAlign: "center" }} className="mesa-label">Verdict em</th>
              </tr>
            </thead>
            <tbody>
              {sleeves.map(s => (
                <tr key={s.name} className="mesa-row mesa-rowhover">
                  <td style={{ padding: "10px 12px" }}>
                    <span className="mesa-h" style={{ fontSize: 12 }}>{s.name}</span>
                  </td>
                  <td style={{ padding: "10px 12px", textAlign: "center" }}>
                    <span className="mesa-num">{s.streams.frozen.n}/{s.contract.eval_at_n}</span>
                  </td>
                  <td style={{ padding: "10px 12px", textAlign: "right" }}>
                    <span className={`mesa-num ${s.streams.frozen.cum_return >= 0 ? "mesa-pos" : "mesa-neg"}`}>
                      {pct(s.streams.frozen.cum_return)}
                    </span>
                  </td>
                  <td style={{ padding: "10px 12px", textAlign: "right" }}>
                    <span className={`mesa-num ${s.streams.operator.cum_return >= 0 ? "mesa-pos" : "mesa-neg"}`}>
                      {pct(s.streams.operator.cum_return)}
                    </span>
                  </td>
                  <td style={{ padding: "10px 12px", textAlign: "right" }}>
                    <span className="mesa-num mesa-neg">{pct(s.streams.operator.max_drawdown)}</span>
                  </td>
                  <td style={{ padding: "10px 12px", textAlign: "center" }}>
                    <span className="mesa-num mesa-amber">{s.months_to_verdict} mo</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ padding: "8px 12px", borderTop: "1px solid var(--line)" }}>
            <span className="mesa-label" style={{ fontSize: 9 }}>
              Retornos operacionais apenas — NÃO são track record validado. O verdict (DSR) só aparece após completar {sleeves[0]?.contract.eval_at_n ?? 24} meses de holdout forward.
            </span>
          </div>
        </div>
      </Panel>

      {/* 6. Alertas de Risco */}
      <Panel title="6 · ALERTAS DE RISCO">
        <div style={{ padding: "12px 14px" }}>
          {sleeves.some(s => s.proposal?.circuit_halted || (s.proposal?.drift_warnings?.length ?? 0) > 0 || (s.proposal?.circuit_reasons?.length ?? 0) > 0) ? (
            <div className="flex flex-col gap-2">
              {sleeves.map(s => {
                const alerts: string[] = [];
                if (s.proposal?.circuit_halted) alerts.push(`🔴 CIRCUIT BREAKER: ${s.proposal.circuit_reasons.join(", ")}`);
                if (s.proposal?.drift_warnings?.length) alerts.push(`🟡 DRIFT: ${s.proposal.drift_warnings.join(", ")}`);
                if (alerts.length === 0) return null;
                return (
                  <div key={s.name} style={{ padding: "6px 0" }}>
                    <span className="mesa-h" style={{ fontSize: 11 }}>{s.name}: </span>
                    {alerts.map((a, i) => (
                      <span key={i} style={{ fontSize: 11, display: "block", marginTop: 2, color: a.startsWith("🔴") ? "var(--red)" : "var(--amber)" }}>
                        {a}
                      </span>
                    ))}
                  </div>
                );
              }).filter(Boolean)}
            </div>
          ) : (
            <span style={{ fontSize: 12, color: "var(--green)" }}>
              ✓ Sem alertas críticos. Todos os gates operando dentro dos limites.
            </span>
          )}
        </div>
      </Panel>

      {/* 7. Próximos Passos */}
      <Panel title="7 · PRÓXIMOS PASSOS">
        <div style={{ padding: "12px 14px" }}>
          <div className="flex flex-col gap-2" style={{ fontSize: 12, lineHeight: 1.7 }}>
            {sleeves.some(s => s.proposal && !s.proposal.operator_decided && !s.proposal.circuit_halted) ? (
              <p style={{ margin: 0 }} className="mesa-amber">
                → Há decisões pendentes no Co-Pilot. Acesse a aba CO-PILOT para APPROVE/SKIP/OVERRIDE.
              </p>
            ) : (
              <p style={{ margin: 0 }} className="mesa-pos">
                → Todas as decisões do mês foram tomadas. Aguarde o próximo rebalanceamento.
              </p>
            )}
            <p style={{ margin: 0, color: "var(--txt)" }}>
              → Próximo verdict: <span className="mesa-amber">{sleeves.reduce((min, s) => Math.min(min, s.months_to_verdict), 99)} meses</span> ({sleeves.find(s => s.months_to_verdict === sleeves.reduce((min, ss) => Math.min(min, ss.months_to_verdict), 99))?.name ?? "—"})
            </p>
            <p style={{ margin: 0, color: "var(--txt)" }}>
              → Monitore a aba RISK durante o mês para flags de drift ou circuit breakers mid-month.
            </p>
            <p style={{ margin: 0, color: "var(--txt)" }}>
              → Se um circuit breaker disparar mid-month, zere a posição correspondente imediatamente na B3.
            </p>
          </div>
        </div>
      </Panel>

      {/* Footer disclaimer */}
      <div style={{ padding: "8px 0" }}>
        <span className="mesa-label" style={{ fontSize: 9, lineHeight: 1.5 }}>
          Este report é gerado automaticamente a partir dos dados do modelo. Não constitui recomendação de investimento.
          Todas as posições estão em fase de accrual (pre-verdict) — nenhum sleeve foi promovido ainda.
          O sistema se recusa a mostrar Sharpe/DSR antes do holdout forward completar.
        </span>
      </div>
    </div>
  );
}
