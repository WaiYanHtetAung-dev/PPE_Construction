import { useEffect, useMemo, useState } from "react";
import { safetyApi } from "./services/safetyApi";
import type { Camera, DashboardSnapshot, Incident, ModelVersion, PageId } from "./types";
import { Button, Card, Icon, Progress, SectionHeader, StatusPill, Toggle } from "./components/ui";

const pages: { id: PageId; label: string; icon: string }[] = [
  { id: "overview", label: "Overview", icon: "overview" },
  { id: "live", label: "Live monitoring", icon: "live" },
  { id: "cameras", label: "Cameras", icon: "camera" },
  { id: "incidents", label: "PPE incidents", icon: "incident" },
  { id: "reports", label: "Reports", icon: "report" },
  { id: "models", label: "Model management", icon: "model" },
  { id: "settings", label: "Settings", icon: "settings" },
];

const titles: Record<PageId, [string, string]> = {
  overview: ["Safety overview", "Monitor compliance and site operations in real time."],
  live: ["Live CCTV monitoring", "AI-assisted video feeds across all active site zones."],
  cameras: ["Camera management", "Configure and monitor connected video sources."],
  incidents: ["PPE incidents", "Review, assign, and resolve safety violations."],
  reports: ["Reports & analytics", "Explore safety trends and export compliance data."],
  models: ["Model management", "Manage detection models and monitor performance."],
  settings: ["Settings", "Configure workspace preferences and alert policies."],
};

function App() {
  const [page, setPage] = useState<PageId>("overview");
  const [sidebar, setSidebar] = useState(false);
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null);
  const [models, setModels] = useState<ModelVersion[]>([]);

  useEffect(() => {
    Promise.all([safetyApi.getDashboard(), safetyApi.getModels()]).then(([data, versions]) => {
      setSnapshot(data);
      setModels(versions);
    });
  }, []);

  if (!snapshot)
    return (
      <div className="loading">
        <span />
        <p>Loading site operations…</p>
      </div>
    );

  const navigate = (id: PageId) => {
    setPage(id);
    setSidebar(false);
  };
  return (
    <div className="app-shell">
      {sidebar && (
        <button
          className="backdrop"
          aria-label="Close navigation"
          onClick={() => setSidebar(false)}
        />
      )}
      <aside className={`sidebar ${sidebar ? "is-open" : ""}`}>
        <div className="brand">
          <span className="brand-mark">
            <Icon name="shield" size={22} />
          </span>
          <span>
            SafeSite<span> AI</span>
          </span>
        </div>
        <nav aria-label="Main navigation">
          <p className="nav-label">WORKSPACE</p>
          {pages.slice(0, 5).map((item) => (
            <NavItem key={item.id} item={item} current={page} onClick={navigate} />
          ))}
          <p className="nav-label nav-label-spaced">SYSTEM</p>
          {pages.slice(5).map((item) => (
            <NavItem key={item.id} item={item} current={page} onClick={navigate} />
          ))}
        </nav>
        <div className="sidebar-status">
          <div>
            <span className="status-dot" />
            <strong>System operational</strong>
          </div>
          <p>All services responding</p>
          <span>Last checked just now</span>
        </div>
        <div className="user-card">
          <div className="avatar">AR</div>
          <div>
            <strong>Alex Rivera</strong>
            <span>Safety Manager</span>
          </div>
          <Icon name="chevron" size={16} />
        </div>
      </aside>

      <main>
        <header className="topbar">
          <button
            className="icon-btn menu-btn"
            aria-label="Open navigation"
            onClick={() => setSidebar(true)}
          >
            <Icon name="menu" />
          </button>
          <div className="mobile-brand">SafeSite AI</div>
          <label className="global-search">
            <Icon name="search" size={18} />
            <input aria-label="Search" placeholder="Search cameras, incidents…" />
            <kbd>⌘ K</kbd>
          </label>
          <div className="top-actions">
            <span className="sync-state">
              <span />
              Live
            </span>
            <button className="icon-btn" aria-label="Notifications">
              <Icon name="bell" />
              <b />
            </button>
            <div className="avatar small">AR</div>
          </div>
        </header>
        <div className="content">
          <div className="page-title">
            <div>
              <h1>{titles[page][0]}</h1>
              <p>{titles[page][1]}</p>
            </div>
            <PageAction page={page} />
          </div>
          {page === "overview" && <Overview data={snapshot} goTo={navigate} />}
          {page === "live" && <LiveMonitoring cameras={snapshot.cameras} />}
          {page === "cameras" && <CameraManagement cameras={snapshot.cameras} />}
          {page === "incidents" && <Incidents incidents={snapshot.incidents} />}
          {page === "reports" && <Reports data={snapshot} />}
          {page === "models" && <Models models={models} />}
          {page === "settings" && <Settings />}
        </div>
      </main>
    </div>
  );
}

function NavItem({
  item,
  current,
  onClick,
}: {
  item: (typeof pages)[number];
  current: PageId;
  onClick: (id: PageId) => void;
}) {
  return (
    <button
      onClick={() => onClick(item.id)}
      className={`nav-item ${current === item.id ? "active" : ""}`}
    >
      <Icon name={item.icon} />
      <span>{item.label}</span>
      {item.id === "incidents" && <em>12</em>}
    </button>
  );
}

function PageAction({ page }: { page: PageId }) {
  if (page === "live") return <Button icon="overview">Grid layout</Button>;
  if (page === "cameras") return <Button icon="plus">Add camera</Button>;
  if (page === "incidents") return <Button icon="download">Export incidents</Button>;
  if (page === "reports") return <Button icon="download">Export report</Button>;
  if (page === "models") return <Button icon="plus">New training run</Button>;
  if (page === "settings") return <Button>Save changes</Button>;
  return (
    <div className="date-control">
      <Icon name="clock" size={17} />
      <span>May 26 – Jun 1, 2025</span>
    </div>
  );
}

function Overview({ data, goTo }: { data: DashboardSnapshot; goTo: (page: PageId) => void }) {
  return (
    <div className="stack">
      <div className="metrics-grid">
        {data.metrics.map((metric) => (
          <Card key={metric.label} className="metric-card">
            <div className={`metric-icon tone-${metric.tone}`}>
              <Icon name={metric.icon} />
            </div>
            <div className="metric-copy">
              <p>{metric.label}</p>
              <strong>{metric.value}</strong>
              <span className={`change ${metric.direction}`}>
                <Icon
                  name={
                    metric.direction === "up"
                      ? "report"
                      : metric.direction === "down"
                        ? "alert"
                        : "clock"
                  }
                  size={13}
                />
                {metric.change}
              </span>
            </div>
          </Card>
        ))}
      </div>

      <div className="overview-grid">
        <Card className="compliance-card">
          <SectionHeader
            title="PPE compliance trend"
            subtitle="Daily compliance rate across all monitored zones"
            action={
              <select aria-label="Compliance period">
                <option>Last 7 days</option>
                <option>Last 30 days</option>
              </select>
            }
          />
          <LineChart values={data.weeklyCompliance} />
        </Card>
        <Card>
          <SectionHeader title="Compliance by PPE" subtitle="Current week" />
          <div className="compliance-list">
            {data.siteCompliance.map((item) => (
              <div key={item.label}>
                <div>
                  <span>{item.label}</span>
                  <strong>{item.value}%</strong>
                </div>
                <Progress value={item.value} color={item.color} />
              </div>
            ))}
          </div>
          <div className="compliance-note">
            <Icon name="shield" size={18} />
            <span>
              <strong>94.8% overall compliance</strong> across 1,284 detections
            </span>
          </div>
        </Card>
      </div>

      <Card>
        <SectionHeader
          title="Recent incidents"
          subtitle="Latest PPE violations requiring attention"
          action={
            <Button variant="ghost" onClick={() => goTo("incidents")}>
              View all <Icon name="chevron" size={15} />
            </Button>
          }
        />
        <IncidentTable incidents={data.incidents.slice(0, 5)} />
      </Card>
    </div>
  );
}

function LineChart({ values }: { values: number[] }) {
  const pts = values
    .map((v, i) => `${i * (100 / (values.length - 1))},${100 - ((v - 80) / 20) * 85}`)
    .join(" ");
  return (
    <div className="line-chart">
      <div className="y-labels">
        <span>100%</span>
        <span>90%</span>
        <span>80%</span>
        <span>70%</span>
      </div>
      <svg
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        aria-label="Compliance rose from 88 to 95 percent over seven days"
      >
        <defs>
          <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#246bfd" stopOpacity=".24" />
            <stop offset="1" stopColor="#246bfd" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={`M0,100 L${pts} L100,100 Z`} fill="url(#area)" />
        <polyline
          points={pts}
          fill="none"
          stroke="#246bfd"
          strokeWidth="2.4"
          vectorEffect="non-scaling-stroke"
        />
        {values.map((v, i) => (
          <circle
            key={i}
            cx={i * (100 / 6)}
            cy={100 - ((v - 80) / 20) * 85}
            r="1.8"
            fill="white"
            stroke="#246bfd"
            strokeWidth="1.2"
          />
        ))}
      </svg>
      <div className="x-labels">
        {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((x) => (
          <span key={x}>{x}</span>
        ))}
      </div>
    </div>
  );
}

function IncidentTable({ incidents }: { incidents: Incident[] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Incident</th>
            <th>Location</th>
            <th>Detected</th>
            <th>Confidence</th>
            <th>Severity</th>
            <th>Status</th>
            <th>
              <span className="sr-only">Action</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {incidents.map((item) => (
            <tr key={item.id}>
              <td>
                <div className="incident-name">
                  <span className={`incident-symbol ${item.severity}`}>
                    <Icon name="incident" size={16} />
                  </span>
                  <div>
                    <strong>{item.type}</strong>
                    <small>{item.id}</small>
                  </div>
                </div>
              </td>
              <td>
                <strong className="body-strong">{item.zone}</strong>
                <small>{item.camera}</small>
              </td>
              <td>{item.occurredAt}</td>
              <td>
                <div className="confidence">
                  <Progress value={item.confidence} />
                  <span>{item.confidence}%</span>
                </div>
              </td>
              <td>
                <StatusPill tone={item.severity}>{item.severity}</StatusPill>
              </td>
              <td>
                <StatusPill
                  tone={
                    item.status === "Resolved"
                      ? "success"
                      : item.status === "Reviewing"
                        ? "warning"
                        : "blue"
                  }
                >
                  {item.status}
                </StatusPill>
              </td>
              <td>
                <button className="row-action" aria-label={`Open ${item.id}`}>
                  <Icon name="chevron" size={16} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LiveMonitoring({ cameras }: { cameras: Camera[] }) {
  const [selected, setSelected] = useState(cameras[0].id);
  const [zone, setZone] = useState("All zones");
  const visible = cameras.filter((c) => zone === "All zones" || c.zone === zone);
  return (
    <div className="stack">
      <div className="toolbar">
        <div className="segmented">
          <button className="active">
            All cameras <span>20</span>
          </button>
          <button>
            Online <span>18</span>
          </button>
          <button>
            Attention <span>2</span>
          </button>
        </div>
        <select value={zone} onChange={(e) => setZone(e.target.value)} aria-label="Filter by zone">
          <option>All zones</option>
          {[...new Set(cameras.map((c) => c.zone))].map((z) => (
            <option key={z}>{z}</option>
          ))}
        </select>
      </div>
      <div className="camera-grid">
        {visible.map((camera) => (
          <button
            key={camera.id}
            onClick={() => setSelected(camera.id)}
            className={`camera-feed ${selected === camera.id ? "selected" : ""}`}
          >
            <img src={camera.image} alt={`Construction site view from ${camera.name}`} />
            <span className="feed-overlay" />
            <div className="feed-top">
              <StatusPill tone={camera.status === "online" ? "success" : "warning"}>
                <span className="live-dot" />
                {camera.status === "online" ? "LIVE" : camera.status.toUpperCase()}
              </StatusPill>
              <span className="ai-chip">
                <Icon name="model" size={13} />
                AI detection
              </span>
            </div>
            {camera.status === "online" && (
              <>
                <span className="detection-box box-one">
                  <b>Person</b>
                  <em>98%</em>
                </span>
                <span className="detection-box box-two">
                  <b>Hard hat</b>
                  <em>96%</em>
                </span>
              </>
            )}
            <div className="feed-bottom">
              <div>
                <strong>{camera.name}</strong>
                <span>
                  {camera.id} · {camera.zone}
                </span>
              </div>
              <span>{camera.fps || "—"} FPS</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function CameraManagement({ cameras }: { cameras: Camera[] }) {
  const [query, setQuery] = useState("");
  const filtered = cameras.filter((c) =>
    `${c.name} ${c.id} ${c.zone}`.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <Card>
      <div className="table-toolbar">
        <label className="inline-search">
          <Icon name="search" size={17} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search cameras"
            placeholder="Search cameras…"
          />
        </label>
        <div>
          <Button variant="secondary" icon="filter">
            Filter
          </Button>
          <span className="result-count">{filtered.length} cameras</span>
        </div>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Camera</th>
              <th>Location</th>
              <th>Status</th>
              <th>Stream</th>
              <th>Detections today</th>
              <th>Last seen</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((c) => (
              <tr key={c.id}>
                <td>
                  <div className="camera-cell">
                    <img src={c.image} alt="" />
                    <div>
                      <strong>{c.name}</strong>
                      <small>{c.id}</small>
                    </div>
                  </div>
                </td>
                <td>{c.zone}</td>
                <td>
                  <StatusPill
                    tone={
                      c.status === "online"
                        ? "success"
                        : c.status === "offline"
                          ? "critical"
                          : "warning"
                    }
                  >
                    <span className="live-dot" />
                    {c.status}
                  </StatusPill>
                </td>
                <td>
                  <strong className="body-strong">{c.resolution}</strong>
                  <small>{c.fps ? `${c.fps} FPS · H.264` : "Stream unavailable"}</small>
                </td>
                <td>
                  <strong className="body-strong">{c.detections}</strong>
                </td>
                <td>{c.lastSeen}</td>
                <td>
                  <button className="more-btn" aria-label={`Options for ${c.name}`}>
                    •••
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function Incidents({ incidents: initial }: { incidents: Incident[] }) {
  const [filter, setFilter] = useState("All");
  const [incidents, setIncidents] = useState(initial);
  const visible = filter === "All" ? incidents : incidents.filter((i) => i.status === filter);
  const resolveFirst = () =>
    setIncidents((items) => items.map((i, idx) => (idx === 0 ? { ...i, status: "Resolved" } : i)));
  return (
    <div className="stack">
      <div className="incident-summary">
        <Card>
          <span>OPEN</span>
          <strong>{incidents.filter((i) => i.status === "Open").length}</strong>
          <small>Requires triage</small>
        </Card>
        <Card>
          <span>IN REVIEW</span>
          <strong>{incidents.filter((i) => i.status === "Reviewing").length}</strong>
          <small>Assigned to team</small>
        </Card>
        <Card>
          <span>RESOLVED THIS WEEK</span>
          <strong>47</strong>
          <small className="positive">↑ 12% from last week</small>
        </Card>
        <Card>
          <span>AVG. RESPONSE TIME</span>
          <strong>4m 12s</strong>
          <small className="positive">↓ 38 sec improvement</small>
        </Card>
      </div>
      <Card>
        <div className="table-toolbar">
          <div className="segmented compact">
            {["All", "Open", "Reviewing", "Resolved"].map((x) => (
              <button key={x} className={filter === x ? "active" : ""} onClick={() => setFilter(x)}>
                {x}
              </button>
            ))}
          </div>
          <Button variant="secondary" icon="filter">
            More filters
          </Button>
        </div>
        <IncidentTable incidents={visible} />
        <div className="table-footer">
          <span>
            Showing {visible.length} of {incidents.length} incidents
          </span>
          <Button variant="secondary" onClick={resolveFirst}>
            Resolve top incident
          </Button>
        </div>
      </Card>
    </div>
  );
}

function Reports({ data }: { data: DashboardSnapshot }) {
  const [range, setRange] = useState("Last 30 days");
  const bars = [24, 31, 28, 42, 35, 52, 39, 44, 31, 27, 34, 22];
  return (
    <div className="stack">
      <div className="report-controls">
        <select value={range} onChange={(e) => setRange(e.target.value)}>
          <option>Last 7 days</option>
          <option>Last 30 days</option>
          <option>Last quarter</option>
        </select>
        <select>
          <option>All site zones</option>
        </select>
        <select>
          <option>All PPE types</option>
        </select>
      </div>
      <div className="metrics-grid report-metrics">
        <Card>
          <p>Total incidents</p>
          <strong>389</strong>
          <span className="positive">↓ 8.3% vs previous period</span>
        </Card>
        <Card>
          <p>Compliance rate</p>
          <strong>94.8%</strong>
          <span className="positive">↑ 2.4% vs previous period</span>
        </Card>
        <Card>
          <p>Critical violations</p>
          <strong>24</strong>
          <span className="negative">↑ 3 requiring attention</span>
        </Card>
        <Card>
          <p>Resolution rate</p>
          <strong>92.1%</strong>
          <span className="positive">↑ 4.7% vs previous period</span>
        </Card>
      </div>
      <div className="overview-grid">
        <Card>
          <SectionHeader title="Incident volume" subtitle={`Violation events · ${range}`} />
          <div className="bar-chart">
            {bars.map((v, i) => (
              <div key={i}>
                <span style={{ height: `${v * 2.1}px` }} />
                <small>{i % 2 === 0 ? `${i + 1}` : ""}</small>
              </div>
            ))}
          </div>
        </Card>
        <Card>
          <SectionHeader title="Incidents by category" subtitle="Share of total violations" />
          <div className="donut-layout">
            <div className="donut">
              <span>
                <strong>389</strong>Total
              </span>
            </div>
            <div className="legend">
              {data.siteCompliance.map((x, i) => (
                <div key={x.label}>
                  <span style={{ background: x.color }} />
                  <p>
                    {x.label}
                    <small>{[41, 29, 18, 12][i]}%</small>
                  </p>
                </div>
              ))}
            </div>
          </div>
        </Card>
      </div>
      <Card>
        <SectionHeader title="Site performance" subtitle="Compliance benchmark by monitored zone" />
        <div className="site-performance">
          {[
            ["Entry Zone", 98],
            ["Foundation East", 95],
            ["North Scaffolding", 91],
            ["Tower Crane Base", 87],
          ].map(([name, value]) => (
            <div key={name}>
              <div>
                <strong>{name}</strong>
                <span>{value}%</span>
              </div>
              <Progress
                value={Number(value)}
                color={Number(value) > 93 ? "#16a34a" : Number(value) > 89 ? "#246bfd" : "#f59e0b"}
              />
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function Models({ models }: { models: ModelVersion[] }) {
  return (
    <div className="stack">
      <Card className="deployed-model">
        <div className="model-icon">
          <Icon name="model" size={28} />
        </div>
        <div className="model-main">
          <span className="eyebrow">CURRENTLY DEPLOYED</span>
          <h2>
            PPE-Detect v3.4.2 <StatusPill tone="success">Healthy</StatusPill>
          </h2>
          <p>Deployed to 18 camera streams · Updated 14 days ago</p>
        </div>
        <div className="model-stats">
          <div>
            <span>Precision</span>
            <strong>96.8%</strong>
          </div>
          <div>
            <span>Recall</span>
            <strong>94.2%</strong>
          </div>
          <div>
            <span>mAP@.50</span>
            <strong>95.4%</strong>
          </div>
        </div>
        <Button variant="secondary">Deployment settings</Button>
      </Card>
      <div className="overview-grid model-grid">
        <Card>
          <SectionHeader title="Model performance" subtitle="Precision by detected class" />
          <div className="compliance-list">
            {[
              ["Hard hat", 98.2],
              ["Safety vest", 96.7],
              ["Person", 95.4],
              ["Safety glasses", 91.8],
              ["Gloves", 88.6],
            ].map(([label, value]) => (
              <div key={label}>
                <div>
                  <span>{label}</span>
                  <strong>{value}%</strong>
                </div>
                <Progress
                  value={Number(value)}
                  color={Number(value) > 95 ? "#16a34a" : "#246bfd"}
                />
              </div>
            ))}
          </div>
        </Card>
        <Card>
          <SectionHeader title="Inference health" subtitle="Last 24 hours" />
          <div className="health-score">
            <div className="health-ring">
              <span>
                <strong>99.7%</strong>Uptime
              </span>
            </div>
            <div>
              <p>
                <span>Median latency</span>
                <strong>42 ms</strong>
              </p>
              <p>
                <span>Frames processed</span>
                <strong>2.8M</strong>
              </p>
              <p>
                <span>Errors</span>
                <strong>0.03%</strong>
              </p>
            </div>
          </div>
        </Card>
      </div>
      <Card>
        <SectionHeader
          title="Model versions"
          subtitle="Train, compare, and deploy detection models"
        />
        <div className="version-list">
          {models.map((m) => (
            <div key={m.version} className="version-row">
              <span className={`version-status ${m.status.toLowerCase()}`}>
                <Icon
                  name={
                    m.status === "Deployed" ? "check" : m.status === "Training" ? "clock" : "model"
                  }
                />
              </span>
              <div className="version-name">
                <strong>{m.version}</strong>
                <span>
                  {m.dataset} · Created {m.createdAt}
                </span>
              </div>
              <StatusPill
                tone={
                  m.status === "Deployed" ? "success" : m.status === "Training" ? "warning" : "blue"
                }
              >
                {m.status}
              </StatusPill>
              {m.status !== "Training" ? (
                <div className="version-metrics">
                  <span>
                    P <b>{m.precision}%</b>
                  </span>
                  <span>
                    R <b>{m.recall}%</b>
                  </span>
                  <span>
                    mAP <b>{m.map}%</b>
                  </span>
                </div>
              ) : (
                <div className="training-progress">
                  <Progress value={68} />
                  <span>68% · 42 min remaining</span>
                </div>
              )}
              <Button variant="secondary">
                {m.status === "Ready" ? "Deploy" : "View details"}
              </Button>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function Settings() {
  const [email, setEmail] = useState(true);
  const [critical, setCritical] = useState(true);
  const [weekly, setWeekly] = useState(false);
  const [retention, setRetention] = useState("90 days");
  const tabs = ["General", "Notifications", "Detection", "Data & privacy", "Integrations"];
  const [tab, setTab] = useState("General");
  return (
    <div className="settings-layout">
      <Card className="settings-tabs">
        {tabs.map((t) => (
          <button key={t} onClick={() => setTab(t)} className={tab === t ? "active" : ""}>
            {t}
            <Icon name="chevron" size={15} />
          </button>
        ))}
      </Card>
      <div className="settings-content">
        <Card>
          <SectionHeader
            title={tab}
            subtitle={
              tab === "General"
                ? "Manage your site identity and regional preferences."
                : `Configure ${tab.toLowerCase()} preferences for this workspace.`
            }
          />
          <div className="form-grid">
            <label>
              <span>Workspace name</span>
              <input defaultValue="Northstar Construction — Phase II" />
            </label>
            <label>
              <span>Site code</span>
              <input defaultValue="NSC-P2-SEA" disabled />
            </label>
            <label>
              <span>Timezone</span>
              <select defaultValue="pst">
                <option value="pst">Pacific Time (UTC−08:00)</option>
                <option>Eastern Time</option>
              </select>
            </label>
            <label>
              <span>Default language</span>
              <select>
                <option>English (US)</option>
                <option>Spanish</option>
              </select>
            </label>
          </div>
        </Card>
        <Card>
          <SectionHeader
            title="Alert preferences"
            subtitle="Choose which events notify your safety team."
          />
          <div className="setting-rows">
            <SettingRow
              title="Critical PPE violations"
              description="Immediately alert when a critical violation is detected."
              checked={critical}
              onChange={setCritical}
            />
            <SettingRow
              title="Email notifications"
              description="Send incident alerts to assigned safety managers."
              checked={email}
              onChange={setEmail}
            />
            <SettingRow
              title="Weekly compliance digest"
              description="Receive a summary every Monday at 8:00 AM."
              checked={weekly}
              onChange={setWeekly}
            />
          </div>
        </Card>
        <Card>
          <SectionHeader
            title="Data retention"
            subtitle="Control how long incident media and metadata are stored."
          />
          <div className="retention-row">
            <div>
              <strong>Incident footage retention</strong>
              <p>Footage is automatically deleted after this period.</p>
            </div>
            <select value={retention} onChange={(e) => setRetention(e.target.value)}>
              <option>30 days</option>
              <option>90 days</option>
              <option>180 days</option>
            </select>
          </div>
        </Card>
      </div>
    </div>
  );
}

function SettingRow({
  title,
  description,
  checked,
  onChange,
}: {
  title: string;
  description: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="setting-row">
      <div>
        <strong>{title}</strong>
        <p>{description}</p>
      </div>
      <Toggle checked={checked} onChange={onChange} label={title} />
    </div>
  );
}

export default App;
