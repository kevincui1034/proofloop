"use client";

/**
 * Overview charts (Recharts client islands). Single-hue or verdict-
 * semantic marks only — no categorical palette to cycle. The pass/blocked
 * areas always render with a legend + direct axis labels (verdict red and
 * green never carry identity alone).
 */
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { DayPoint } from "@/lib/queries/overview";

const AXIS = { fill: "var(--faint)", fontSize: 11 };
const TOOLTIP_STYLE = {
  backgroundColor: "var(--surface-3)",
  border: "1px solid var(--line-2)",
  borderRadius: 6,
  color: "var(--ink)",
  fontSize: 12,
};

export function PassRateChart({ data }: { data: DayPoint[] }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
        <CartesianGrid stroke="var(--line)" strokeDasharray="0" vertical={false} />
        <XAxis dataKey="day" tick={AXIS} stroke="var(--line-2)" />
        <YAxis tick={AXIS} stroke="var(--line-2)" allowDecimals={false} />
        <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ stroke: "var(--line-2)" }} />
        <Legend wrapperStyle={{ fontSize: 12, color: "var(--body)" }} />
        <Area
          type="monotone"
          dataKey="passed"
          name="allowed"
          stackId="runs"
          stroke="var(--verdict-green)"
          fill="var(--verdict-green)"
          fillOpacity={0.25}
          strokeWidth={2}
        />
        <Area
          type="monotone"
          dataKey="blocked"
          name="blocked"
          stackId="runs"
          stroke="var(--verdict-red)"
          fill="var(--verdict-red)"
          fillOpacity={0.25}
          strokeWidth={2}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function FailureClassChart({
  data,
}: {
  data: { name: string; count: number }[];
}) {
  const height = Math.max(120, data.length * 36 + 40);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart
        data={data}
        layout="vertical"
        margin={{ top: 8, right: 24, left: 40, bottom: 0 }}
      >
        <CartesianGrid stroke="var(--line)" horizontal={false} />
        <XAxis type="number" tick={AXIS} stroke="var(--line-2)" allowDecimals={false} />
        <YAxis
          type="category"
          dataKey="name"
          tick={{ ...AXIS, fontFamily: "var(--font-geist-mono)" }}
          stroke="var(--line-2)"
          width={140}
        />
        <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: "var(--surface-3)" }} />
        <Bar
          dataKey="count"
          name="catches"
          fill="var(--amber)"
          fillOpacity={0.85}
          radius={[0, 4, 4, 0]}
          barSize={18}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}
