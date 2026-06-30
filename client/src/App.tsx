import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import NotFound from "@/pages/NotFound";
import { Route, Switch } from "wouter";
import ErrorBoundary from "./components/ErrorBoundary";
import { ThemeProvider } from "./contexts/ThemeContext";
import Home from "./pages/Home";
import Portfolio from "./pages/Portfolio";
import ArcApp from "./arc/ArcApp";

function Router() {
  return (
    <Switch>
      {/* ARC 2.0 Mesa routes (primary) */}
      <Route path="/" component={ArcApp} />
      <Route path="/co-pilot" component={ArcApp} />
      <Route path="/holdout" component={ArcApp} />
      <Route path="/risk" component={ArcApp} />
      <Route path="/macro" component={ArcApp} />
      <Route path="/research" component={ArcApp} />
      <Route path="/ledger" component={ArcApp} />
      <Route path="/report" component={ArcApp} />

      {/* Legacy v4.6 dashboard (accessible at /legacy) */}
      <Route path="/legacy" component={Home} />
      <Route path="/portfolio" component={Portfolio} />

      <Route path="/404" component={NotFound} />
      <Route component={NotFound} />
    </Switch>
  );
}

function App() {
  return (
    <ErrorBoundary>
      <ThemeProvider defaultTheme="dark" switchable>
        <TooltipProvider>
          <Toaster />
          <Router />
        </TooltipProvider>
      </ThemeProvider>
    </ErrorBoundary>
  );
}

export default App;
