import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useKeyboardNav } from "../useKeyboardNav";

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function makeItems(tickers: string[]) {
  return tickers.map((ticker) => ({ ticker }));
}

function fire(key: string) {
  const event = new KeyboardEvent("keydown", {
    key,
    bubbles: true,
    cancelable: true,
  });
  window.dispatchEvent(event);
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe("useKeyboardNav", () => {
  const items = makeItems(["AAPL", "TSLA", "NVDA", "MSFT"]);

  let onSelect: ReturnType<typeof vi.fn>;
  let onOpen: ReturnType<typeof vi.fn>;
  let onRefresh: ReturnType<typeof vi.fn>;
  let onTogglePreset: ReturnType<typeof vi.fn>;
  let onTabSwitch: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    onSelect = vi.fn();
    onOpen = vi.fn();
    onRefresh = vi.fn();
    onTogglePreset = vi.fn();
    onTabSwitch = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function renderNav(selectedIndex = 0) {
    return renderHook(
      ({ idx }) =>
        useKeyboardNav({
          items,
          selectedIndex: idx,
          onSelect,
          onOpen,
          onRefresh,
          onTogglePreset,
          onTabSwitch,
        }),
      { initialProps: { idx: selectedIndex } },
    );
  }

  /* ---- j key increments selectedIndex ---- */
  it("j key increments selectedIndex", () => {
    renderNav(1);
    act(() => fire("j"));
    expect(onSelect).toHaveBeenCalledWith(2);
  });

  it("ArrowDown increments selectedIndex", () => {
    renderNav(0);
    act(() => fire("ArrowDown"));
    expect(onSelect).toHaveBeenCalledWith(1);
  });

  it("j key clamps at last item", () => {
    renderNav(3);
    act(() => fire("j"));
    expect(onSelect).toHaveBeenCalledWith(3); // stays at last
  });

  /* ---- k key decrements selectedIndex ---- */
  it("k key decrements selectedIndex", () => {
    renderNav(2);
    act(() => fire("k"));
    expect(onSelect).toHaveBeenCalledWith(1);
  });

  it("ArrowUp decrements selectedIndex", () => {
    renderNav(1);
    act(() => fire("ArrowUp"));
    expect(onSelect).toHaveBeenCalledWith(0);
  });

  it("k key clamps at zero", () => {
    renderNav(0);
    act(() => fire("k"));
    expect(onSelect).toHaveBeenCalledWith(0); // stays at 0
  });

  /* ---- Enter calls onOpen with correct ticker ---- */
  it("Enter calls onOpen with correct ticker", () => {
    renderNav(2);
    act(() => fire("Enter"));
    expect(onOpen).toHaveBeenCalledWith("NVDA");
  });

  it("Enter does nothing when no selection", () => {
    renderNav(-1);
    act(() => fire("Enter"));
    expect(onOpen).not.toHaveBeenCalled();
  });

  /* ---- Does NOT fire when input is focused ---- */
  it("does NOT fire when input is focused", () => {
    renderNav(0);

    // Create and focus an input element
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();

    act(() => fire("j"));
    expect(onSelect).not.toHaveBeenCalled();

    act(() => fire("Enter"));
    expect(onOpen).not.toHaveBeenCalled();

    act(() => fire("f"));
    expect(onRefresh).not.toHaveBeenCalled();

    // Cleanup
    document.body.removeChild(input);
  });

  it("does NOT fire when textarea is focused", () => {
    renderNav(0);

    const ta = document.createElement("textarea");
    document.body.appendChild(ta);
    ta.focus();

    act(() => fire("j"));
    expect(onSelect).not.toHaveBeenCalled();

    document.body.removeChild(ta);
  });

  /* ---- 1-6 calls onTabSwitch ---- */
  it("1-6 calls onTabSwitch with correct tab index", () => {
    renderNav(0);
    for (let i = 1; i <= 6; i++) {
      act(() => fire(String(i)));
    }
    expect(onTabSwitch).toHaveBeenCalledTimes(6);
    expect(onTabSwitch).toHaveBeenCalledWith(1);
    expect(onTabSwitch).toHaveBeenCalledWith(2);
    expect(onTabSwitch).toHaveBeenCalledWith(3);
    expect(onTabSwitch).toHaveBeenCalledWith(4);
    expect(onTabSwitch).toHaveBeenCalledWith(5);
    expect(onTabSwitch).toHaveBeenCalledWith(6);
  });

  it("does not call onTabSwitch for 0, 7, 8, 9", () => {
    renderNav(0);
    act(() => fire("0"));
    act(() => fire("7"));
    act(() => fire("8"));
    act(() => fire("9"));
    expect(onTabSwitch).not.toHaveBeenCalled();
  });

  /* ---- Escape resets selection ---- */
  it("Escape resets selection to -1", () => {
    renderNav(2);
    act(() => fire("Escape"));
    expect(onSelect).toHaveBeenCalledWith(-1);
  });

  /* ---- f triggers refresh ---- */
  it("f key calls onRefresh", () => {
    renderNav(0);
    act(() => fire("f"));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  /* ---- l/s/h toggle presets ---- */
  it("l key toggles LONGS preset", () => {
    renderNav(0);
    act(() => fire("l"));
    expect(onTogglePreset).toHaveBeenCalledWith("LONGS");
  });

  it("s key toggles SHORTS preset", () => {
    renderNav(0);
    act(() => fire("s"));
    expect(onTogglePreset).toHaveBeenCalledWith("SHORTS");
  });

  it("h key toggles HOLD preset", () => {
    renderNav(0);
    act(() => fire("h"));
    expect(onTogglePreset).toHaveBeenCalledWith("HOLD");
  });
});
