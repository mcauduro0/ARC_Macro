import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Route, Switch } from "wouter";
import ArcApp from "./arc/ArcApp";
import ErrorBoundary from "./components/ErrorBoundary";
import { ThemeProvider } from "./contexts/ThemeContext";
import Home from "./pages/Home";
import Portfolio from "./pages/Portfolio";

function Router() {
  // ARC Macro 2.0 full pivot: the autonomy-first console is the app. The legacy v4.6 dashboard stays
  // reachable at /legacy during the migration; /portfolio is preserved.
  return (
    <Switch>
      <Route path={"/legacy"} component={Home} />
      <Route path={"/portfolio"} component={Portfolio} />
      <Route component={ArcApp} />
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
