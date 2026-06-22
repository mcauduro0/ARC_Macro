// The ARC Macro 2.0 app: the Mesa shell + the autonomy-first routes. The legacy v4.6 dashboard stays
// reachable at /legacy during the pivot.
import { Route, Switch } from "wouter";
import "./mesa.css";
import { Shell } from "./Shell";
import { Command } from "./pages/Command";
import { Placeholder } from "./pages/Placeholder";
import { useAutonomyState } from "./useAutonomy";

export default function ArcApp() {
  const { data } = useAutonomyState();
  return (
    <Shell asOf={data?.meta?.as_of ?? null}>
      <Switch>
        <Route path="/" component={Command} />
        <Route path="/co-pilot">
          {() => <Placeholder area="Co-pilot" note="propose → decide workspace · operator ledger · 3-stream view (frozen / live / operator)" />}
        </Route>
        <Route path="/holdout">
          {() => <Placeholder area="Holdout & Governance" note="eval_at_n countdown · deflation basis · pre-registration provenance · pooled holdout" />}
        </Route>
        <Route path="/risk">
          {() => <Placeholder area="Risk" note="VaR/ES pre-trade gate · DCC-GARCH covariance · circuit breaker · vol-target vs VaR-limit leverage" />}
        </Route>
        <Route path="/macro">
          {() => <Placeholder area="Macro Engine" note="r* with credible intervals · regime probabilities · state variables · FX fair value · DI curve · nowcast" />}
        </Route>
        <Route path="/research">
          {() => <Placeholder area="Research / Diagnostics" note="feature selection · SHAP · the honest nulls (positioning / real-curve / sizing) · as-of & leakage canaries" />}
        </Route>
        <Route path="/ledger">
          {() => <Placeholder area="Ledger / Audit" note="immutable record explorer · hash provenance · accrual log" />}
        </Route>
        <Route>{() => <Placeholder area="Not found" note="No such area." />}</Route>
      </Switch>
    </Shell>
  );
}
