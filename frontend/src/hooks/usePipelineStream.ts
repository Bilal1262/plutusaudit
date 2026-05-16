import { usePipeline } from "../context/PipelineContext";

/**
 * Convenience alias matching the lifted-SSE docs — delegates to PipelineProvider state.
 */
export function usePipelineStream() {
  return usePipeline();
}
