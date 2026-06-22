// The ARC Macro 2.0 app: the Mesa shell + the autonomy-first routes. The legacy v4.6 dashboard stays
// reachable at /legacy during the pivot.
import { Route, Switch } from "wouter";
import "./mesa.css";
import { Shell } from "./Shell";
import { Command } from "./pages/Command";
import { CoPilot } from "./pages/CoPilot";
import { Holdout } from "./pages/Holdout";
import { Risk } from "./pages/Risk";
import { Research } from "./pages/Research";
import { Ledger } from "./pages/Ledger";
import { Placeholder } from "./pages/Placeholder";
import { useAutonomyState } from "./useAutonomy";

export default function ArcApp() {
  const { data } = useAutonomyState();
  return (
    <Shell asOf={data?.meta?.as_of ?? null}>
      <Switch>
        <Route path="/" component={Command} />
        <Route path="/co-pilot" component={CoPilot} />
        <Route path="/holdout" component={Holdout} />
        <Route path="/risk" component={Risk} />
        <Route path="/macro">
          {() => <Placeholder area="Macro Engine" note="r* with credible intervals · regime probabilities · state variables · FX fair value · DI curve · nowcast" />}
        </Route>
        <Route path="/research" component={Research} />
        <Route path="/ledger" component={Ledger} />
        <Route>{() => <Placeholder area="Not found" note="No such area." />}</Route>
      </Switch>
    </Shell>
  );
}
