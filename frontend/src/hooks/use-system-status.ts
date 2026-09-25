import { useQuery } from "@tanstack/react-query";
import { getSystemStatus } from "@/lib/api";

/** Real backend configuration (LLM, warehouse, GitHub, cache). Cached for a minute. */
export function useSystemStatus() {
  return useQuery({ queryKey: ["system", "status"], queryFn: getSystemStatus, staleTime: 60_000 });
}
