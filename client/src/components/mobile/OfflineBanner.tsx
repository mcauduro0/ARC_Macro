/**
 * OfflineBanner — Shows when the app is offline with last sync time
 */

import { motion, AnimatePresence } from 'framer-motion';
import { WifiOff, RefreshCw } from 'lucide-react';

interface Props {
  online: boolean;
  lastSync: number | null;
}

export function OfflineBanner({ online, lastSync }: Props) {
  const formatLastSync = (ts: number | null) => {
    if (!ts) return 'nunca';
    const diff = Date.now() - ts;
    if (diff < 60000) return 'agora';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}min atrás`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h atrás`;
    return new Date(ts).toLocaleDateString('pt-BR');
  };

  return (
    <AnimatePresence>
      {!online && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.3 }}
          className="bg-amber-500/10 border-b border-amber-500/20 overflow-hidden"
        >
          <div className="flex items-center justify-between px-4 py-2">
            <div className="flex items-center gap-2">
              <WifiOff className="w-3.5 h-3.5 text-amber-400" />
              <span className="text-[11px] font-medium text-amber-400">
                Modo Offline
              </span>
            </div>
            <span className="text-[10px] text-amber-400/70">
              Último sync: {formatLastSync(lastSync)}
            </span>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
