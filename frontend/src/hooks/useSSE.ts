"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { streamUrl } from "@/lib/api";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export type SSEEventType =
  | "agent_start"
  | "agent_progress"
  | "agent_complete"
  | "debate_round"
  | "final_decision"
  | "error";

export interface SSEEvent {
  type: SSEEventType;
  agent?: string;
  message: string;
  data?: Record<string, unknown>;
  timestamp: string;
}

export interface UseSSEReturn {
  events: SSEEvent[];
  isConnected: boolean;
  error: string | null;
  connect: (analysisId: string) => void;
  disconnect: () => void;
}

/* ------------------------------------------------------------------ */
/*  Hook                                                               */
/* ------------------------------------------------------------------ */

export function useSSE(): UseSSEReturn {
  const [events, setEvents] = useState<SSEEvent[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sourceRef = useRef<EventSource | null>(null);

  const disconnect = useCallback(() => {
    if (sourceRef.current) {
      sourceRef.current.close();
      sourceRef.current = null;
    }
    setIsConnected(false);
  }, []);

  const connect = useCallback(
    (analysisId: string) => {
      disconnect();
      setEvents([]);
      setError(null);

      const url = streamUrl(analysisId);
      const es = new EventSource(url);
      sourceRef.current = es;

      es.onopen = () => setIsConnected(true);

      es.onmessage = (ev) => {
        try {
          const parsed: SSEEvent = JSON.parse(ev.data);
          setEvents((prev) => [...prev, parsed]);

          if (parsed.type === "final_decision" || parsed.type === "error") {
            es.close();
            sourceRef.current = null;
            setIsConnected(false);
          }
        } catch {
          console.warn("SSE: failed to parse event", ev.data);
        }
      };

      es.onerror = () => {
        setError("Connection lost. The analysis may still be running.");
        es.close();
        sourceRef.current = null;
        setIsConnected(false);
      };
    },
    [disconnect],
  );

  // cleanup on unmount
  useEffect(() => {
    return () => {
      sourceRef.current?.close();
    };
  }, []);

  return { events, isConnected, error, connect, disconnect };
}
