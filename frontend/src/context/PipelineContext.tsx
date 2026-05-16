import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type MutableRefObject,
  type ReactNode,
} from "react";

import { streamProcessing } from "../api";
import { buildPipelineFromEvents } from "../utils/buildPipeline";
import type { AgentEvent, PipelineResult } from "../types";

export type PipelineRunStatus =
  | "idle"
  | "processing"
  | "complete"
  | "error";

interface PipelineContextValue {
  events: AgentEvent[];
  pipeline: PipelineResult;
  jobId: string | null;
  status: PipelineRunStatus;
  streamDone: boolean;
  activeFilename: string | null;
  streamError: string | null;
  /** Job id for which the new-vendor approval banner was dismissed — survives remount via context state */
  vendorPromptDismissedJobId: string | null;
  dismissVendorBanner: () => void;
  sseRef: MutableRefObject<EventSource | null>;
  attachPipelineStream: (jobId: string, filename: string) => void;
  resetPipeline: () => void;
}

const PipelineContext = createContext<PipelineContextValue | null>(null);

export function PipelineProvider({ children }: { children: ReactNode }) {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<PipelineRunStatus>("idle");
  const [streamDone, setStreamDone] = useState(false);
  const [activeFilename, setActiveFilename] = useState<string | null>(null);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [vendorPromptDismissedJobId, setVendorPromptDismissedJobId] = useState<
    string | null
  >(null);

  const sseRef = useRef<EventSource | null>(null);

  const pipeline = useMemo(() => buildPipelineFromEvents(events), [events]);

  const closeStream = useCallback(() => {
    sseRef.current?.close();
    sseRef.current = null;
  }, []);

  const resetPipeline = useCallback(() => {
    closeStream();
    setEvents([]);
    setJobId(null);
    setStatus("idle");
    setStreamDone(false);
    setActiveFilename(null);
    setStreamError(null);
    setVendorPromptDismissedJobId(null);
  }, [closeStream]);

  const dismissVendorBanner = useCallback(() => {
    if (jobId) setVendorPromptDismissedJobId(jobId);
  }, [jobId]);

  const attachPipelineStream = useCallback(
    (nextJobId: string, filename: string) => {
      closeStream();
      setVendorPromptDismissedJobId(null);
      setEvents([]);
      setJobId(nextJobId);
      setActiveFilename(filename);
      setStreamError(null);
      setStreamDone(false);
      setStatus("processing");

      sseRef.current = streamProcessing(
        nextJobId,
        (ev) => {
          setEvents((prev) => [...prev, ev]);
        },
        () => {
          setStreamDone(true);
          setStatus("complete");
          sseRef.current = null;
        },
        () => {
          setStreamDone(true);
          setStatus((prev) => (prev === "complete" ? "complete" : "error"));
          setStreamError((prev) => prev ?? "Stream connection lost");
          sseRef.current = null;
        },
      );
    },
    [closeStream],
  );

  const value = useMemo(
    (): PipelineContextValue => ({
      events,
      pipeline,
      jobId,
      status,
      streamDone,
      activeFilename,
      streamError,
      vendorPromptDismissedJobId,
      dismissVendorBanner,
      sseRef,
      attachPipelineStream,
      resetPipeline,
    }),
    [
      events,
      pipeline,
      jobId,
      status,
      streamDone,
      activeFilename,
      streamError,
      vendorPromptDismissedJobId,
      dismissVendorBanner,
      attachPipelineStream,
      resetPipeline,
    ],
  );

  return (
    <PipelineContext.Provider value={value}>
      {children}
    </PipelineContext.Provider>
  );
}

export function usePipeline(): PipelineContextValue {
  const ctx = useContext(PipelineContext);
  if (!ctx) {
    throw new Error("usePipeline must be used within PipelineProvider");
  }
  return ctx;
}
