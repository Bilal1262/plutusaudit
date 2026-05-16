import type { AccountantResult, RetrievedChunk } from "../types";

/** Compare cited standard to chunk standard (lenient, handles compound labels). */
function standardsMatchLoose(citedStd: string, chunkStd: string): boolean {
  const cited = citedStd.trim().toLowerCase().replace(/\s/g, "");
  const std = (chunkStd || "").trim().toLowerCase().replace(/\s/g, "");
  if (!cited) return false;
  if (!std) return false;
  return std.includes(cited) || cited.includes(std);
}

/**
 * Prefer the retrieved chunk whose **standard** matches what the Accountant
 * cited (avoids showing an unrelated topic when another chunk ranked higher).
 * Among standard matches, prefer best RAG rank.
 */
export function pickCitationChunk(
  accountant: AccountantResult,
): RetrievedChunk | undefined {
  const chunks = accountant.retrieved_chunks;
  if (!chunks?.length) return undefined;

  const citedStd = (accountant.standard_cited || "").trim();

  const byStandard = chunks.filter((c) =>
    standardsMatchLoose(citedStd, c.standard || ""),
  );

  const pool = byStandard.length > 0 ? byStandard : chunks;
  const sorted = [...pool].sort(
    (a, b) => (a.rank ?? 99) - (b.rank ?? 99),
  );
  return sorted[0];
}
