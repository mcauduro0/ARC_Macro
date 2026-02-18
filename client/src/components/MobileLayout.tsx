/**
 * MobileLayout — Bottom tab bar navigation for mobile devices
 * 
 * 5 tabs: Overview, Modelo, Portfólio, Alertas, Mais
 * Includes compact sticky header with key metrics
 * Touch-optimized with 44px minimum tap targets
 */

import { useState, useCallback, useRef, useEffect, type ReactNode } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  LayoutDashboard,
  Brain,
  Briefcase,
  Bell,
  MoreHorizontal,
  TrendingUp,
  TrendingDown,
  Minus,
  Zap,
  Shield,
  AlertTriangle,
  Activity,
  RefreshCw,
  Loader2,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { MacroDashboard, useModelStatus, useRunModel } from '@/hooks/useModelData';
import { toast } from 'sonner';
import { ThemeToggle } from '@/components/ThemeToggle';

// ── Types ──────────────────────────────────────────────────────────────────

export type MobileTab = 'overview' | 'modelo' | 'portfolio' | 'alertas' | 'mais';

interface MobileLayoutProps {
  dashboard: MacroDashboard;
  source?: 'live' | 'embedded';
  lastUpdated?: Date | null;
  activeTab: MobileTab;
  onTabChange: (tab: MobileTab) => void;
  children: ReactNode;
  alertCount?: number;
}

// ── Helpers ────────────────────────────────────────────────────────────────

function getScoreColor(score: number) {
  if (score > 1) return 'text-emerald-400';
  if (score > 0.5) return 'text-emerald-400/80';
  if (score > -0.5) return 'text-amber-400';
  if (score > -1) return 'text-rose-400/80';
  return 'text-rose-400';
}

function getDirectionColor(direction: string | undefined) {
  if (!direction) return 'text-amber-400';
  if (direction?.includes('LONG') && direction?.includes('BRL')) return 'text-emerald-400';
  if (direction?.includes('SHORT') && direction?.includes('BRL')) return 'text-rose-400';
  return 'text-amber-400';
}

function getDirectionIcon(direction: string | undefined) {
  if (!direction) return <Minus className="w-3.5 h-3.5" />;
  if (direction?.includes('LONG') && direction?.includes('BRL')) return <TrendingDown className="w-3.5 h-3.5" />;
  if (direction?.includes('SHORT') && direction?.includes('BRL')) return <TrendingUp className="w-3.5 h-3.5" />;
  return <Minus className="w-3.5 h-3.5" />;
}

function getRegimeIcon(regime: string) {
  if (regime === 'Carry') return <Zap className="w-3 h-3" />;
  if (regime === 'RiskOff') return <Shield className="w-3 h-3" />;
  if (regime === 'StressDom') return <AlertTriangle className="w-3 h-3" />;
  return <Activity className="w-3 h-3" />;
}

function getRegimeColor(regime: string) {
  if (regime === 'Carry') return 'text-emerald-400 bg-emerald-400/10 border-emerald-400/30';
  if (regime === 'RiskOff') return 'text-rose-400 bg-rose-400/10 border-rose-400/30';
  if (regime === 'StressDom') return 'text-amber-400 bg-amber-400/10 border-amber-400/30';
  return 'text-cyan-400 bg-cyan-400/10 border-cyan-400/30';
}

// ── Tab Config ─────────────────────────────────────────────────────────────

const TABS: { id: MobileTab; label: string; icon: typeof LayoutDashboard }[] = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'modelo', label: 'Modelo', icon: Brain },
  { id: 'portfolio', label: 'Portfólio', icon: Briefcase },
  { id: 'alertas', label: 'Alertas', icon: Bell },
  { id: 'mais', label: 'Mais', icon: MoreHorizontal },
];

// ── Mobile Header ──────────────────────────────────────────────────────────

function MobileHeader({
  dashboard,
  source,
}: {
  dashboard: MacroDashboard;
  source?: 'live' | 'embedded';
}) {
  const [expanded, setExpanded] = useState(false);
  const d = dashboard;
  const regime = d.current_regime || d.dominant_regime || 'N/A';
  const scoreColor = getScoreColor(d.score_total || 0);
  const dirColor = getDirectionColor(d.direction);
  const regimeColor = getRegimeColor(regime);
  const { data: status } = useModelStatus();
  const runModel = useRunModel();
  const isRunning = status?.isRunning || runModel.isPending;

  const handleRefresh = useCallback(() => {
    runModel.mutate(undefined, {
      onSuccess: (data) => {
        if (data.success) {
          toast.success('Modelo em execução...');
        } else {
          toast.error(data.error || 'Erro ao iniciar modelo');
        }
      },
      onError: (err) => toast.error('Erro: ' + err.message),
    });
  }, [runModel]);

  return (
    <motion.header
      initial={{ opacity: 0, y: -5 }}
      animate={{ opacity: 1, y: 0 }}
      className="sticky top-0 z-50 bg-background/95 backdrop-blur-md border-b border-border/50"
    >
      {/* Main row — always visible */}
      <div className="flex items-center justify-between px-4 h-12">
        <div className="flex items-center gap-2">
          <div className={`w-1.5 h-1.5 rounded-full ${source === 'live' ? 'bg-emerald-400' : 'bg-amber-400'} animate-pulse`} />
          <span className="text-xs font-semibold tracking-wide uppercase text-foreground/90">
            USDBRL
          </span>
          <span className="font-data text-lg font-bold text-primary">
            {d.current_spot?.toFixed(4) || 'N/A'}
          </span>
        </div>

        <div className="flex items-center gap-3">
          <div className={`flex items-center gap-1 ${scoreColor}`}>
            <span className="font-data text-sm font-bold">
              {d.score_total != null ? ((d.score_total > 0 ? '+' : '') + d.score_total.toFixed(2)) : '--'}
            </span>
          </div>
          <div className={`flex items-center gap-0.5 px-2 py-0.5 rounded-full border text-[10px] font-semibold ${regimeColor}`}>
            {getRegimeIcon(regime)}
            <span className="uppercase">{regime}</span>
          </div>
          <button
            onClick={() => setExpanded(!expanded)}
            className="p-1 -mr-1 text-muted-foreground"
          >
            {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Expanded row — extra details */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden border-t border-border/30"
          >
            <div className="px-4 py-2.5 flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className={`flex items-center gap-1 ${dirColor}`}>
                  {getDirectionIcon(d.direction)}
                  <span className="text-[11px] font-semibold uppercase">
                    {d.direction || 'NEUTRAL'}
                  </span>
                </div>
                <span className="text-[10px] text-muted-foreground font-data">
                  {d.run_date}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <ThemeToggle size="sm" />
                <button
                  onClick={handleRefresh}
                  disabled={isRunning}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary/10 border border-primary/20 text-primary text-[11px] font-semibold disabled:opacity-50 active:scale-95 transition-transform"
                >
                  {isRunning ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <RefreshCw className="w-3.5 h-3.5" />
                  )}
                  {isRunning ? 'Running...' : 'Refresh'}
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.header>
  );
}

// ── Bottom Tab Bar ─────────────────────────────────────────────────────────

function BottomTabBar({
  activeTab,
  onTabChange,
  alertCount = 0,
}: {
  activeTab: MobileTab;
  onTabChange: (tab: MobileTab) => void;
  alertCount?: number;
}) {
  return (
    <nav className="fixed bottom-0 left-0 right-0 z-50 bg-background/95 backdrop-blur-md border-t border-border/50 safe-area-bottom">
      <div className="flex items-center justify-around h-16 px-2">
        {TABS.map((tab) => {
          const isActive = activeTab === tab.id;
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              onClick={() => onTabChange(tab.id)}
              className={`
                relative flex flex-col items-center justify-center gap-0.5 w-16 h-12 rounded-xl
                transition-all duration-200 active:scale-90
                ${isActive
                  ? 'text-primary'
                  : 'text-muted-foreground'
                }
              `}
            >
              <div className="relative">
                <Icon className={`w-5 h-5 ${isActive ? 'stroke-[2.5]' : 'stroke-[1.5]'}`} />
                {tab.id === 'alertas' && alertCount > 0 && (
                  <span className="absolute -top-1 -right-1.5 min-w-[14px] h-[14px] flex items-center justify-center rounded-full bg-rose-500 text-[8px] font-bold text-white px-0.5">
                    {alertCount > 99 ? '99+' : alertCount}
                  </span>
                )}
              </div>
              <span className={`text-[10px] font-medium ${isActive ? 'text-primary' : 'text-muted-foreground/70'}`}>
                {tab.label}
              </span>
              {isActive && (
                <motion.div
                  layoutId="tab-indicator"
                  className="absolute -top-px left-3 right-3 h-0.5 bg-primary rounded-full"
                  transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                />
              )}
            </button>
          );
        })}
      </div>
    </nav>
  );
}

// ── Swipe Handler ──────────────────────────────────────────────────────────

function useSwipeNavigation(activeTab: MobileTab, onTabChange: (tab: MobileTab) => void) {
  const touchStartX = useRef(0);
  const touchStartY = useRef(0);
  const tabOrder: MobileTab[] = ['overview', 'modelo', 'portfolio', 'alertas', 'mais'];

  const handleTouchStart = useCallback((e: TouchEvent) => {
    touchStartX.current = e.touches[0].clientX;
    touchStartY.current = e.touches[0].clientY;
  }, []);

  const handleTouchEnd = useCallback((e: TouchEvent) => {
    const deltaX = e.changedTouches[0].clientX - touchStartX.current;
    const deltaY = e.changedTouches[0].clientY - touchStartY.current;
    
    // Only trigger if horizontal swipe is dominant and > 80px
    if (Math.abs(deltaX) > 80 && Math.abs(deltaX) > Math.abs(deltaY) * 1.5) {
      const currentIndex = tabOrder.indexOf(activeTab);
      if (deltaX < 0 && currentIndex < tabOrder.length - 1) {
        onTabChange(tabOrder[currentIndex + 1]);
      } else if (deltaX > 0 && currentIndex > 0) {
        onTabChange(tabOrder[currentIndex - 1]);
      }
    }
  }, [activeTab, onTabChange, tabOrder]);

  useEffect(() => {
    document.addEventListener('touchstart', handleTouchStart, { passive: true });
    document.addEventListener('touchend', handleTouchEnd, { passive: true });
    return () => {
      document.removeEventListener('touchstart', handleTouchStart);
      document.removeEventListener('touchend', handleTouchEnd);
    };
  }, [handleTouchStart, handleTouchEnd]);
}

// ── Main Layout ────────────────────────────────────────────────────────────

export function MobileLayout({
  dashboard,
  source,
  lastUpdated,
  activeTab,
  onTabChange,
  children,
  alertCount = 0,
}: MobileLayoutProps) {
  useSwipeNavigation(activeTab, onTabChange);

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <MobileHeader dashboard={dashboard} source={source} />
      
      <main className="flex-1 pb-20 overflow-x-hidden">
        <AnimatePresence mode="wait">
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, x: 10 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -10 }}
            transition={{ duration: 0.15 }}
          >
            {children}
          </motion.div>
        </AnimatePresence>
      </main>

      <BottomTabBar
        activeTab={activeTab}
        onTabChange={onTabChange}
        alertCount={alertCount}
      />
    </div>
  );
}
