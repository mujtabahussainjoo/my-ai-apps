import { cn } from "@/lib/utils";

/**
 * Renders a question prompt, promoting fenced code blocks (inlined diagrams,
 * programs, config, terminal output) to real <pre> blocks instead of leaving
 * raw ``` markers in flowing text. Everything outside the fences keeps its
 * line breaks via .prose-answer.
 */
export function QuestionPrompt({ text, className }: { text: string; className?: string }) {
  const segments = (text ?? "").split("```");

  return (
    <div className={cn("space-y-3", className)}>
      {segments.map((segment, i) => {
        if (i % 2 === 1) {
          // Strip an optional language tag on the fence line: ```text
          const body = segment.replace(/^[^\n]*\n?/, "");
          return (
            <pre
              key={i}
              className="overflow-x-auto whitespace-pre rounded-lg border border-white/10 bg-black/30 px-3 py-2.5 text-[13px] leading-relaxed text-foreground/85"
            >
              {body}
            </pre>
          );
        }
        const prose = segment.trim();
        return prose ? (
          <p key={i} className="prose-answer font-medium leading-relaxed">
            {prose}
          </p>
        ) : null;
      })}
    </div>
  );
}
