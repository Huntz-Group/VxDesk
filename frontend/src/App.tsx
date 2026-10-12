import { useEffect } from 'react';
import { Route, Routes, useNavigate, NavLink } from 'react-router';
import { AssistantPanel } from './components/AssistantPanel';
import { RecorderBar, RecordButton } from './components/RecorderBar';
import { RecorderReviewModal } from './components/RecorderReviewModal';
import { OfflineBanner, StatusBadge } from './components/StatusBadge';
import { SparkleIcon } from './icons';
import { EditorPage } from './pages/Editor';
import { RemotePage } from './pages/Remote';
import { WorkflowListPage } from './pages/WorkflowList';
import { useAssistantStore } from './assistantStore';
import { useAppStore } from './store';

function AssistantToggle() {
  const toggle = useAssistantStore((s) => s.toggle);
  const open = useAssistantStore((s) => s.open);
  const status = useAssistantStore((s) => s.status);
  const refreshStatus = useAssistantStore((s) => s.refreshStatus);

  useEffect(() => {
    void refreshStatus();
    const t = setInterval(() => void refreshStatus(), 30000);
    return () => clearInterval(t);
  }, [refreshStatus]);

  const dotClass =
    status === null ? 'beige' : !status.configured ? 'beige' : status.reachable ? 'sage' : 'rose';
  const dotTitle =
    status === null
      ? 'Assistant status unknown'
      : !status.configured
        ? 'Assistant not set up yet'
        : status.reachable
          ? `Assistant connected${status.model ? ` · ${status.model}` : ''}`
          : "Assistant can't reach its model";

  return (
    <button className={`btn small ai-toggle${open ? ' active' : ''}`} onClick={toggle} title={dotTitle}>
      <SparkleIcon size={13} />
      Assistant
      <span className={`ai-toggle-dot ${dotClass}`} />
    </button>
  );
}

export default function App() {
  const navigate = useNavigate();
  const refreshSystem = useAppStore((s) => s.refreshSystem);
  const loadCatalog = useAppStore((s) => s.loadCatalog);

  useEffect(() => {
    void refreshSystem();
    void loadCatalog();
  }, [refreshSystem, loadCatalog]);

  return (
    <div className="app-shell">
      <div className="topbar">
        <div className="brand" onClick={() => navigate('/')}>
          <span style={{ width: 10, height: 10, borderRadius: 4, background: 'var(--coral)', alignSelf: 'center' }} />
          <span className="wordmark">VxDesk</span>
        </div>
        <nav className="topnav">
          <NavLink to="/" end className={({ isActive }) => (isActive ? 'active' : '')}>
            Workflows
          </NavLink>
          <NavLink to="/remote" className={({ isActive }) => (isActive ? 'active' : '')}>
            Remote
          </NavLink>
        </nav>
        <span className="spacer" />
        <RecordButton />
        <AssistantToggle />
        <StatusBadge />
      </div>
      <OfflineBanner />
      <Routes>
        <Route path="/" element={<WorkflowListPage />} />
        <Route path="/workflow/:id" element={<EditorPage />} />
        <Route path="/remote" element={<RemotePage />} />
      </Routes>
      <AssistantPanel />
      <RecorderBar />
      <RecorderReviewModal />
    </div>
  );
}
