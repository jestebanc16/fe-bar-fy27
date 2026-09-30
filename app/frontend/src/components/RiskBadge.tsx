import type { RiskBand } from "../types";
import { riskBadgeClasses } from "../format";

export default function RiskBadge({ band }: { band: RiskBand }) {
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium capitalize ${riskBadgeClasses[band]}`}
    >
      {band}
    </span>
  );
}
