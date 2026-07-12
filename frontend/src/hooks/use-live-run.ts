import { useEffect, useState } from "react";
import { peekRun, subscribeRun } from "@/lib/api";
import type { Run } from "@/lib/types";

/** Subscribes to the mock run store; starts the simulated agent for running runs. */
export function useLiveRun(id: string): Run | undefined {
  const [run, setRun] = useState<Run | undefined>(undefined);

  useEffect(() => {
    let mounted = true;
    setRun(peekRun(id));
    const unsub = subscribeRun(id, () => {
      if (mounted) setRun(peekRun(id));
    });
    return () => {
      mounted = false;
      unsub();
    };
  }, [id]);

  return run;
}