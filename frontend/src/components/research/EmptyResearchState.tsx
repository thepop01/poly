"use client";

const EXAMPLES = [
  "Find up to 100 wallets with more than 70% win rate in Sports → Cricket → T20, minimum 20 resolved positions.",
  "For those wallets, show markets where at least 25% currently hold a position.",
  "For this market, rank participating wallets by Cricket win rate and summarize their outcomes.",
];

export default function EmptyResearchState({ onPick }: { onPick: (prompt: string) => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 text-xl text-primary">
        ◈
      </div>
      <div>
        <h2 className="text-lg font-bold text-foreground">Start a research thread</h2>
        <p className="mt-1 max-w-md text-sm text-subtle">
          Each tab is an independent chat. Ask for wallet discovery, market
          activity, open-position overlap, or outcome consensus — evidence
          lands in panels on the right.
        </p>
      </div>
      <div className="flex w-full max-w-lg flex-col gap-2">
        {EXAMPLES.map((example) => (
          <button
            key={example}
            type="button"
            onClick={() => onPick(example)}
            className="rounded-lg border border-border bg-surface px-3 py-2 text-left text-sm text-muted-fg hover:border-primary/40 hover:text-foreground"
          >
            {example}
          </button>
        ))}
      </div>
    </div>
  );
}
