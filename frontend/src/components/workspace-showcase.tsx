export function WorkspaceShowcase({ compact = false }: { compact?: boolean }) {
  return (
    <div
      className={`hero-preview-frame device-showcase${compact ? " compact" : ""}`}
    >
      <div className="device-desktop">
        <div className="device-browser">
          <span />
          <span />
          <span />
          <small>SentinelOps · Overview</small>
        </div>
        <div className="device-desktop-screen">
          <img
            src="/images/workspace-overview.png"
            alt="SentinelOps sample dashboard with incident evidence, human review, and investigation analytics"
            width={1280}
            height={1545}
          />
        </div>
      </div>
      <div className="device-phone">
        <div className="device-phone-camera" />
        <div className="device-phone-screen">
          <img
            src="/images/workspace-mobile.png"
            alt="Mobile SentinelOps dashboard with incident review and analytics"
            width={390}
            height={1600}
          />
        </div>
      </div>
      <div className="device-feature-labels">
        <span>Evidence</span>
        <span>Human approval</span>
        <span>Investigation analytics</span>
      </div>
    </div>
  );
}
