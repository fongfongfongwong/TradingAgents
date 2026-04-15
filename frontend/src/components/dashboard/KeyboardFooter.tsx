"use client";

const SHORTCUTS = [
  { keys: "1-6", desc: "switch tab" },
  { keys: "j/k", desc: "row nav" },
  { keys: "Enter", desc: "inspector" },
  { keys: "F", desc: "fast refresh" },
  { keys: "\u2318R", desc: "deep debate" },
  { keys: "L/S", desc: "longs/shorts" },
  { keys: "\u2318K", desc: "palette" },
] as const;

export default function KeyboardFooter() {
  return (
    <footer className="flex h-[26px] shrink-0 items-center justify-between border-t border-[#1c2230] bg-[#0d1218] px-4 py-1 font-mono text-[9px] text-[#6e7a91]">
      <div className="flex items-center gap-3">
        {SHORTCUTS.map((s, i) => (
          <span key={s.keys} className="flex items-center gap-1">
            {i > 0 && <span className="mr-1 text-[#47536a]">&middot;</span>}
            <kbd className="font-bold text-[#4fc3f7]">
              {s.keys}
            </kbd>
            <span>{s.desc}</span>
          </span>
        ))}
      </div>

      <span>
        agents parallelized · sem=20 · sonnet-4-5 synth · Tier 0 (18 factors)
      </span>
    </footer>
  );
}
