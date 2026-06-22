// Typed React Query hooks over the tRPC autonomy proxy (-> FastAPI -> arc.autonomy).
import { trpc } from "@/lib/trpc";

export function useAutonomyState() {
  return trpc.autonomy.state.useQuery(undefined, {
    refetchInterval: 60_000, // the dump job refreshes monthly; poll lightly for ledger writes
    staleTime: 30_000,
    retry: 1,
  });
}

export function useDecide() {
  const utils = trpc.useUtils();
  return trpc.autonomy.decide.useMutation({
    onSuccess: () => {
      utils.autonomy.state.invalidate();
    },
  });
}

/** Raw immutable ledger records for one sleeve (decisions / realizations / operator decisions). */
export function useLedger(strategy: string) {
  return trpc.autonomy.ledger.useQuery(
    { strategy },
    { staleTime: 30_000, retry: 1, enabled: Boolean(strategy) },
  );
}
