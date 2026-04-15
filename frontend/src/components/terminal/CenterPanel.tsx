"use client";

import type { TabId } from "@/app/page";
import ChartTab from "@/components/tabs/ChartTab";
import AnalysisTab from "@/components/tabs/AnalysisTab";
import OptionsTab from "@/components/tabs/OptionsTab";
import HoldingsTab from "@/components/tabs/HoldingsTab";
import BacktestTab from "@/components/tabs/BacktestTab";
import SignalsTab from "@/components/tabs/SignalsTab";
import SettingsTab from "@/components/tabs/SettingsTab";

const TABS: { id: TabId; label: string }[] = [
  { id: "chart", label: "Chart" },
  { id: "analysis", label: "Analysis" },
  { id: "signals", label: "Signals" },
  { id: "options", label: "Options" },
  { id: "holdings", label: "Holdings" },
  { id: "backtest", label: "Backtest" },
  { id: "settings", label: "Settings" },
];

interface Props {
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
}

export default function CenterPanel({ activeTab, onTabChange }: Props) {
  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Tab bar */}
      <div className="flex shrink-0 border-b border-white/[0.08] bg-[#0f1011]">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            className={`px-4 py-2 text-xs font-medium transition-colors ${
              activeTab === tab.id
                ? "border-b-2 border-[#5e6ad2] text-[#f7f8f8]"
                : "text-[#8a8f98] hover:text-[#d0d6e0]"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto bg-[#08090a] p-4">
        {activeTab === "chart" && <ChartTab />}
        {activeTab === "analysis" && <AnalysisTab />}
        {activeTab === "signals" && <SignalsTab />}
        {activeTab === "options" && <OptionsTab />}
        {activeTab === "holdings" && <HoldingsTab />}
        {activeTab === "backtest" && <BacktestTab />}
        {activeTab === "settings" && <SettingsTab />}
      </div>
    </div>
  );
}
