import { MacroDashboard, useModelStatus, useRunModel } from '@/hooks/useModelData';
import { TrendingUp, TrendingDown, Minus, Activity, Shield, Zap, AlertTriangle, RefreshCw, Wifi, WifiOff, Loader2 } from 'lucide-react';
import { motion } from 'framer-motion';
import { toast } from 'sonner';

interface Props {
  dashboard: MacroDashboard;
  source?: 'live' | 'embedded';
  lastUpdated?: Date | null;
}

function getDirectionIcon(direction: string) {
  if (direction.includes('LONG') && direction.includes('BRL')) return <TrendingDown className="w-4 h-4" />;
  if (direction.includes('SHORT') && direction.includes('BRL')) return <TrendingUp className="w-4 h-4" />;
  return <Minus className="w-4 h-4" />;
}

function getDirectionColor(direction: string) {
  if (direction.includes('LONG') && direction.includes('BRL')) return 'text-emerald-400';
  if (direction.includes('SHORT') && direction.includes('BRL')) return 'text-rose-400';
  return 'text-amber-400';
}

function getScoreColor(score: number) {
  if (score > 1) return 'text-emerald-400 glow-green';
  if (score > 0.5) return 'text-emerald-400/80';
  if (score > -0.5) return 'text-amber-400';
  if (score > -1) return 'text-rose-400/80';
  return 'text-rose-400 glow-red';
}

function getRegimeIcon(regime: string) {
  if (regime === 'Carry') return <Zap className="w-3.5 h-3.5" />;
  if (regime === 'RiskOff') return <Shield className="w-3.5 h-3.5" />;
  if (regime === 'StressDom') return <AlertTriangle className="w-3.5 h-3.5" />;
  return <Activity className="w-3.5 h-3.5" />;
}

function getRegimeColor(regime: string) {
  if (regime === 'Carry') return 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20';
  if (regime === 'RiskOff') return 'text-rose-400 bg-rose-400/10 border-rose-400/20';
  if (regime === 'StressDom') return 'text-amber-400 bg-amber-400/10 border-amber-400/20';
  return 'text-cyan-400 bg-cyan-400/10 border-cyan-400/20';
}

export function StatusBar({ dashboard, source = 'embedded', lastUpdated }: Props) {
  const d = dashboard;
  const regime = d.current_regime || d.dominant_regime || 'N/A';
  const dirColor = getDirectionColor(d.direction);
  const scoreColor = getScoreColor(d.score_total);
  const regimeColor = getRegimeColor(regime);
  const { data: status } = useModelStatus();
  const runModel = useRunModel();

  const handleRefresh = () => {
    runModel.mutate(undefined, {
      onSuccess: (data) => {
        if (data.success) {
          toast.success('Macro Risk OS em execução. Dados atualizados em ~5 min.');
        } else {
          toast.error(data.error || 'Erro ao iniciar modelo');
        }
      },
      onError: (err) => {
        toast.error('Erro: ' + err.message);
      },
    });
  };

  const isRunning = status?.isRunning || runModel.isPending;

  return (
    <motion.header
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="sticky top-0 z-50 border-b border-border/50 bg-background/95 backdrop-blur-sm"
    >
      <div className="container">
        <div className="flex items-center justify-between h-16">
          {/* Left: Logo + Spot */}
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-3">
              <div className={`w-2 h-2 rounded-full ${source === 'live' ? 'bg-emerald-400' : 'bg-amber-400'} animate-pulse`} />
              <h1 className="text-sm font-semibold tracking-wide uppercase text-foreground/90">
                Macro Risk OS
              </h1>
              {source === 'live' ? (
                <span className="hidden lg:flex items-center gap-1 text-[10px] text-emerald-400/70 uppercase tracking-wider">
                  <Wifi className="w-3 h-3" /> Live
                </span>
              ) : (
                <span className="hidden lg:flex items-center gap-1 text-[10px] text-amber-400/70 uppercase tracking-wider">
                  <WifiOff className="w-3 h-3" /> Static
                </span>
              )}
            </div>
            <div className="hidden sm:flex items-center gap-2 pl-6 border-l border-border/50">
              <span className="text-xs text-muted-foreground uppercase tracking-wider">USDBRL</span>
              <span className="font-data text-2xl font-bold text-primary glow-cyan">
                {d.current_spot?.toFixed(4) || 'N/A'}
              </span>
            </div>
          </div>

          {/* Center: Score + Direction */}
          <div className="hidden md:flex items-center gap-8">
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground uppercase tracking-wider">Score</span>
              <span className={`font-data text-xl font-bold ${scoreColor}`}>
                {d.score_total != null ? ((d.score_total > 0 ? '+' : '') + d.score_total.toFixed(2)) : 'N/A'}
              </span>
            </div>
            <div className={`flex items-center gap-1.5 ${dirColor}`}>
              {getDirectionIcon(d.direction)}
              <span className="text-xs font-semibold uppercase tracking-wider">
                {d.direction}
              </span>
            </div>
          </div>

          {/* Right: Regime + Refresh + Date */}
          <div className="flex items-center gap-4">
            <div className={`hidden sm:flex items-center gap-1.5 px-3 py-1 rounded-full border ${regimeColor}`}>
              {getRegimeIcon(regime)}
              <span className="text-xs font-semibold uppercase tracking-wider">
                {regime}
              </span>
            </div>
            <button
              onClick={handleRefresh}
              disabled={isRunning}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-border/50 hover:border-primary/50 hover:bg-primary/5 transition-all text-muted-foreground hover:text-primary disabled:opacity-50 disabled:cursor-not-allowed"
              title={isRunning ? 'Modelo em execução...' : 'Atualizar modelo'}
            >
              {isRunning ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <RefreshCw className="w-3.5 h-3.5" />
              )}
              <span className="hidden lg:inline text-[10px] uppercase tracking-wider font-medium">
                {isRunning ? 'Running' : 'Refresh'}
              </span>
            </button>
            <span className="text-xs text-muted-foreground font-data">
              {d.run_date}
            </span>
          </div>
        </div>
      </div>
    </motion.header>
  );
}
