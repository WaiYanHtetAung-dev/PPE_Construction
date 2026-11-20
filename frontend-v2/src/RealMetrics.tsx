
import { Card, Icon } from "./components/ui";

type Props = {
  siteCount: number;
  cameraCount: number;
  incidentTotal: number | null;
};

export default function RealMetrics({
  siteCount,
  cameraCount,
  incidentTotal,
}: Props) {
  const metrics = [
    {
      label: "Registered sites",
      value: String(siteCount),
      note: "From PostgreSQL",
      icon: "overview",
      tone: "blue",
    },
    {
      label: "Configured cameras",
      value: String(cameraCount),
      note: "Configuration count, not online count",
      icon: "camera",
      tone: "green",
    },
    {
      label: "Recorded incidents",
      value: incidentTotal === null ? "—" : String(incidentTotal),
      note: "All recorded incident statuses",
      icon: "incident",
      tone: "orange",
    },
    {
      label: "Live CCTV status",
      value: "N/A",
      note: "Stream monitoring not enabled",
      icon: "live",
      tone: "blue",
    },
  ];

  return (
    <div id="overview" className="metrics-grid">
      {metrics.map((metric) => (
        <Card key={metric.label} className="metric-card">
          <div className={`metric-icon tone-${metric.tone}`}>
            <Icon name={metric.icon} size={22} />
          </div>
          <div className="metric-copy">
            <p>{metric.label}</p>
            <strong>{metric.value}</strong>
            <span className="change">{metric.note}</span>
          </div>
        </Card>
      ))}
    </div>
  );
}
