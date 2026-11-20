
import { useState, type ReactNode } from "react";
import { Icon } from "./components/ui";

type Props = {
  children: ReactNode;
  userEmail: string;
  onLogout: () => void;
};

const navigation = [
  { id: "overview", label: "Overview", icon: "overview" },
  { id: "cameras", label: "Sites & Cameras", icon: "camera" },
  { id: "incidents", label: "PPE Incidents", icon: "incident" },
];

export default function FigmaShell({
  children,
  userEmail,
  onLogout,
}: Props) {
  const [sidebar, setSidebar] = useState(false);

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

          {navigation.map((item) => (
            <a
              key={item.id}
              href={`#${item.id}`}
              className="nav-item"
              onClick={() => setSidebar(false)}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
            </a>
          ))}
        </nav>

        <div className="sidebar-status">
          <div>
            <strong>Integration environment</strong>
          </div>
          <p>Real database records</p>
          <span>CCTV and AI detection not enabled</span>
        </div>

        <div className="user-card">
          <div>
            <strong title={userEmail}>Authenticated user</strong>
            <span>Integration test session</span>
          </div>
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

          <div className="top-actions">
            <span className="text-sm text-slate-500">
              Test environment
            </span>

            <button
              type="button"
              onClick={onLogout}
              className="rounded-lg bg-slate-900 px-4 py-2 text-white"
            >
              Sign out
            </button>
          </div>
        </header>

        <div className="content">{children}</div>
      </main>
    </div>
  );
}
