/**
 * useOffline — Hook for offline status awareness
 * Provides online/offline state and cached data utilities
 */

import { useState, useEffect, useCallback } from 'react';
import { isOnline, onOnlineStatusChange, cacheModelData, getCachedModelData } from '@/lib/pwa';

export function useOffline() {
  const [online, setOnline] = useState(() => isOnline());
  const [lastSync, setLastSync] = useState<number | null>(null);

  useEffect(() => {
    const unsubscribe = onOnlineStatusChange(setOnline);
    return unsubscribe;
  }, []);

  const saveToCache = useCallback(async (key: string, data: any) => {
    await cacheModelData(key, data);
    setLastSync(Date.now());
  }, []);

  const loadFromCache = useCallback(async (key: string) => {
    const result = await getCachedModelData(key);
    if (result) {
      setLastSync(result.timestamp);
    }
    return result;
  }, []);

  return {
    online,
    lastSync,
    saveToCache,
    loadFromCache,
  };
}
