/**
 * MobileAlertasTab — Alerts, Pipeline status, Data Source Health
 * Touch-optimized alert cards with severity indicators
 */

import { useState, type ReactNode } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ChevronDown,
  Bell,
  Activity,
  Database,
  AlertTriangle,
  CheckCircle2,
  Info,
  XCircle,
  Clock,
  Zap,
} from 'lucide-react';
import { ModelAlertsPanel } from '@/components/ModelAlertsPanel';
import { PipelinePanel } from '@/components/PipelinePanel';
import { DataSourceHealthPanel } from '@/components/DataSourceHealthPanel';

// ── Collapsible Section ────────────────────────────────────────────────────

function MobileSection({
  title,
  icon: Icon,
  children,
  defaultOpen = false,
  badge,
  badgeColor,
}: {
  title: string;
  icon: typeof Bell;
  children: ReactNode;
  defaultOpen?: boolean;
  badge?: string;
  badgeColor?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="border-b border-border/30 last:border-b-0">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3.5 active:bg-accent/30 transition-colors"
      >
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
            <Icon className="w-4 h-4 text-primary" />
          </div>
          <span className="text-sm font-medium text-foreground">{title}</span>
          {badge && (
            <span className={`px-1.5 py-0.5 rounded-md text-[10px] font-semibold ${badgeColor || 'bg-primary/10 text-primary'}`}>
              {badge}
            </span>
          )}
        </div>
        <motion.div
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: 0.2 }}
        >
          <ChevronDown className="w-4 h-4 text-muted-foreground" />
        </motion.div>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25 }}
            className="overflow-hidden"
          >
            <div className="px-2 pb-4">
              {children}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────

export function MobileAlertasTab() {
  return (
    <div className="py-2">
      <div className="px-4 py-2 mb-1">
        <h2 className="text-lg font-semibold text-foreground">Alertas & Status</h2>
        <p className="text-xs text-muted-foreground">Notificações, pipeline e saúde dos dados</p>
      </div>

      <MobileSection
        title="Alertas do Modelo"
        icon={Bell}
        defaultOpen={true}
        badge="Ativo"
        badgeColor="bg-rose-400/10 text-rose-400"
      >
        <div className="overflow-x-auto -mx-2">
          <ModelAlertsPanel />
        </div>
      </MobileSection>

      <MobileSection
        title="Pipeline Automático"
        icon={Activity}
        badge="Diário"
        badgeColor="bg-emerald-400/10 text-emerald-400"
      >
        <div className="overflow-x-auto -mx-2">
          <PipelinePanel />
        </div>
      </MobileSection>

      <MobileSection
        title="Saúde dos Dados"
        icon={Database}
      >
        <div className="overflow-x-auto -mx-2">
          <DataSourceHealthPanel />
        </div>
      </MobileSection>
    </div>
  );
}
