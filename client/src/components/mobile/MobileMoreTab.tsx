/**
 * MobileMoreTab — Additional panels: Equilibrium, Regime, What-If, Sovereign, Changelog
 * Collapsible sections for less-frequently accessed data
 */

import { useState, type ReactNode } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ChevronDown,
  Scale,
  Layers,
  Sliders,
  Globe,
  History,
  Briefcase,
} from 'lucide-react';
import { EquilibriumPanel } from '@/components/EquilibriumPanel';
import { RegimeWeightHeatmap } from '@/components/RegimeWeightHeatmap';
import { WhatIfPanel } from '@/components/WhatIfPanel';
import { SovereignRiskPanel } from '@/components/SovereignRiskPanel';
import { ModelChangelogPanel } from '@/components/ModelChangelogPanel';
import type { MacroDashboard } from '@/hooks/useModelData';

interface Props {
  dashboard: MacroDashboard;
}

// ── Collapsible Section ────────────────────────────────────────────────────

function MobileSection({
  title,
  icon: Icon,
  children,
  defaultOpen = false,
  description,
}: {
  title: string;
  icon: typeof Scale;
  children: ReactNode;
  defaultOpen?: boolean;
  description?: string;
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
          <div className="text-left">
            <span className="text-sm font-medium text-foreground block">{title}</span>
            {description && (
              <span className="text-[10px] text-muted-foreground">{description}</span>
            )}
          </div>
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

export function MobileMoreTab({ dashboard }: Props) {
  return (
    <div className="py-2">
      <div className="px-4 py-2 mb-1">
        <h2 className="text-lg font-semibold text-foreground">Mais</h2>
        <p className="text-xs text-muted-foreground">Equilíbrio, regime, cenários e histórico</p>
      </div>

      <MobileSection
        title="Equilíbrio r*"
        icon={Scale}
        defaultOpen={true}
        description="Composite rate e decomposição"
      >
        <div className="overflow-x-auto -mx-2">
          <EquilibriumPanel dashboard={dashboard} />
        </div>
      </MobileSection>

      <MobileSection
        title="Regime × Pesos"
        icon={Layers}
        description="Heatmap de pesos por regime"
      >
        <div className="overflow-x-auto -mx-2">
          <RegimeWeightHeatmap dashboard={dashboard} />
        </div>
      </MobileSection>

      <MobileSection
        title="What-If Cenários"
        icon={Sliders}
        description="Análise de sensibilidade r*"
      >
        <div className="overflow-x-auto -mx-2">
          <WhatIfPanel dashboard={dashboard} />
        </div>
      </MobileSection>

      <MobileSection
        title="Risco Soberano"
        icon={Globe}
        description="CDS, EMBI, fiscal"
      >
        <div className="overflow-x-auto -mx-2">
          <SovereignRiskPanel dashboard={dashboard} />
        </div>
      </MobileSection>

      <MobileSection
        title="Changelog"
        icon={History}
        description="Histórico de versões do modelo"
      >
        <div className="overflow-x-auto -mx-2">
          <ModelChangelogPanel />
        </div>
      </MobileSection>
    </div>
  );
}
