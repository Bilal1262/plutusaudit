import { BookText } from "lucide-react";
import type { RetrievedChunk } from "../types";

interface Props {
  standard: string;
  paragraph: string;
  topic?: string;
  ruleText?: string;
  chunk?: RetrievedChunk;
}

/**
 * Looks like a legal citation card — clean, formal, slightly elevated.
 * Used inside the Accountant agent expanded panel.
 */
export default function CitationCard({
  standard,
  paragraph,
  topic,
  ruleText,
  chunk,
}: Props) {
  const _topic = topic ?? chunk?.topic ?? "";
  const _rule = ruleText ?? chunk?.rule ?? "";
  return (
    <div className="card p-4 border-l-4 border-veridian-500/70">
      <div className="flex items-start gap-3">
        <div className="grid h-9 w-9 place-items-center rounded-lg bg-veridian-600/20 ring-1 ring-veridian-500/30">
          <BookText className="h-4 w-4 text-veridian-300" />
        </div>
        <div className="flex-1">
          <div className="text-xs uppercase tracking-wider text-veridian-300">
            {standard} · {paragraph}
          </div>
          {_topic && (
            <div className="mt-0.5 text-sm font-semibold text-white">
              {_topic}
            </div>
          )}
          {_rule && (
            <div className="mt-2 text-[13px] leading-relaxed text-slate-300">
              {_rule}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
