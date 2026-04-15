"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { streamUrl, streamUrlV3 } from "@/lib/api";

/* ------------------------------------------------------------------ */
/*  Types matching both v2 and v3 backend SSE events                   */
/* ------------------------------------------------------------------ */

export type SSEEventType =
  // v2 events
  | "agent_start"
  | "agent_complete"
  | "analysis_complete"
  // v3 pipeline events
  | "materialized"
  | "screened"
  | "thesis_complete"
  | "antithesis_complete"
  | "base_rate_complete"
  | "synthesis_complete"
  | "risk_complete"
  | "pipeline_complete"
  | "pipeline_failed"
  | "error";

export interface SSEEvent {
  type: SSEEventType;
  agent?: string;
  data?: Record<string, unknown>;
  timestamp: string;
}

export interface UseSSEReturn {
  events: SSEEvent[];
  isConnected: boolean;
  error: string | null;
  connect: (analysisId: string) => void;
  connectV3: (analysisId: string) => void;
  disconnect: () => void;
}

/* ------------------------------------------------------------------ */
/*  All v3 event type names                                            */
/* ------------------------------------------------------------------ */

const V3_EVENTS: SSEEventType[] = [
  "materialized",
  "screened",
  "thesis_complete",
  "antithesis_complete",
  "base_rate_complete",
  "synthesis_complete",
  "risk_complete",
  "pipeline_complete",
  "pipeline_failed",
];

const V3_TERMINAL: Set<SSEEventType> = new Set([
  "pipeline_complete",
  "pipeline_failed",
  "error",
]);

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

  const makeHandler =
    (es: EventSource, type: SSEEventType) => (ev: MessageEvent) => {
      try {
        const data = JSON.parse(ev.data);
        const event: SSEEvent = {
          type,
          agent: data.agent,
          data,
          timestamp: new Date().toISOString(),
        };
        setEvents((prev) => [...prev, event]);

        if (V3_TERMINAL.has(type)) {
          es.close();
          sourceRef.current = null;
          setIsConnected(false);
        }
      } catch {
        // ignore unparseable frames
      }
    };

  // v2 connect (legacy)
  const connect = useCallback(
    (analysisId: string) => {
      disconnect();
      setEvents([]);
      setError(null);

      const es = new EventSource(streamUrl(analysisId));
      sourceRef.current = es;
      es.onopen = () => setIsConnected(true);
      es.onerror = () => {
        setError("Connection lost.");
        es.close();
        sourceRef.current = null;
        setIsConnected(false);
      };

      es.addEventListener("agent_start", makeHandler(es, "agent_start"));
      es.addEventListener("agent_complete", makeHandler(es, "agent_complete"));
      es.addEventListener("analysis_complete", makeHandler(es, "analysis_complete"));
    },
    [disconnect],
  );

  // v3 connect (debate pipeline)
  const connectV3 = useCallback(
    (analysisId: string) => {
      disconnect();
      setEvents([]);
      setError(null);

      const es = new EventSource(streamUrlV3(analysisId));
      sourceRef.current = es;
      es.onopen = () => setIsConnected(true);
      es.onerror = () => {
        setError("Connection lost. Pipeline may still be running.");
        es.close();
        sourceRef.current = null;
        setIsConnected(false);
      };

      // Register ALL v3 event types
      for (const eventType of V3_EVENTS) {
        es.addEventListener(eventType, makeHandler(es, eventType));
      }
    },
    [disconnect],
  );

  useEffect(() => {
    return () => {
      sourceRef.current?.close();
    };
  }, []);

  return { events, isConnected, error, connect, connectV3, disconnect };
}
