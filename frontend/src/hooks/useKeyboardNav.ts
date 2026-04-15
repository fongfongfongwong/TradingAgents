import { useCallback, useEffect } from "react";

import type { PresetKey } from "@/lib/presetFilters";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface UseKeyboardNavOptions {
  readonly items: readonly { ticker: string }[];
  readonly selectedIndex: number;
  readonly onSelect: (index: number) => void;
  readonly onOpen: (ticker: string) => void;
  readonly onRefresh: () => void;
  readonly onTogglePreset: (key: PresetKey) => void;
  readonly onTabSwitch: (tabIndex: number) => void;
}

/* ------------------------------------------------------------------ */
/*  Guard: skip when an input-like element is focused                   */
/* ------------------------------------------------------------------ */

function isInputFocused(): boolean {
  const tag = document.activeElement?.tagName?.toUpperCase();
  if (!tag) return false;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

/* ------------------------------------------------------------------ */
/*  Hook                                                               */
/* ------------------------------------------------------------------ */

export function useKeyboardNav(options: UseKeyboardNavOptions): void {
  const {
    items,
    selectedIndex,
    onSelect,
    onOpen,
    onRefresh,
    onTogglePreset,
    onTabSwitch,
  } = options;

  const handler = useCallback(
    (e: KeyboardEvent) => {
      if (isInputFocused()) return;

      const key = e.key;

      // j / ArrowDown -- move selection down
      if (key === "j" || key === "ArrowDown") {
        e.preventDefault();
        const next = Math.min(selectedIndex + 1, items.length - 1);
        onSelect(next);
        return;
      }

      // k / ArrowUp -- move selection up
      if (key === "k" || key === "ArrowUp") {
        e.preventDefault();
        const next = Math.max(selectedIndex - 1, 0);
        onSelect(next);
        return;
      }

      // Enter -- open selected ticker in inspector
      if (key === "Enter") {
        e.preventDefault();
        if (selectedIndex >= 0 && selectedIndex < items.length) {
          onOpen(items[selectedIndex].ticker);
        }
        return;
      }

      // Escape -- deselect
      if (key === "Escape") {
        e.preventDefault();
        onSelect(-1);
        return;
      }

      // f -- fast refresh
      if (key === "f") {
        e.preventDefault();
        onRefresh();
        return;
      }

      // l -- toggle LONGS preset
      if (key === "l") {
        e.preventDefault();
        onTogglePreset("LONGS");
        return;
      }

      // s -- toggle SHORTS preset
      if (key === "s") {
        e.preventDefault();
        onTogglePreset("SHORTS");
        return;
      }

      // h -- toggle HOLD preset
      if (key === "h") {
        e.preventDefault();
        onTogglePreset("HOLD");
        return;
      }

      // 1-7 -- switch tabs
      const num = parseInt(key, 10);
      if (num >= 1 && num <= 7) {
        e.preventDefault();
        onTabSwitch(num);
        return;
      }
    },
    [items, selectedIndex, onSelect, onOpen, onRefresh, onTogglePreset, onTabSwitch],
  );

  useEffect(() => {
    window.addEventListener("keydown", handler);
    return () => {
      window.removeEventListener("keydown", handler);
    };
  }, [handler]);
}
