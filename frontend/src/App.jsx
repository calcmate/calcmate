import { useState } from 'react'
import { Routes, Route } from 'react-router-dom'
import Header from './components/Header.jsx'
import Sidebar from './components/Sidebar.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Scheduler from './pages/Scheduler.jsx'
import CalculatorScheduler from './pages/CalculatorScheduler.jsx'
import BlogScheduler from './pages/BlogScheduler.jsx'
import Calculators from './pages/Calculators.jsx'
import CalculatorDetail from './pages/CalculatorDetail.jsx'
import Logs from './pages/Logs.jsx'
import Settings from './pages/Settings.jsx'
import Health from './pages/Health.jsx'
import Publish from './pages/Publish.jsx'
import Trash from './pages/Trash.jsx'
import Blog from './pages/Blog.jsx'
import Cost from './pages/Cost.jsx'
import StrategyRoom from './pages/StrategyRoom.jsx'
import Workboard from './pages/Workboard.jsx'
import Sites from './pages/Sites.jsx'
import SiteWizard from './pages/SiteWizard.jsx'
import AiAssistant from './pages/AiAssistant.jsx'
import AiWorkspace from './pages/AiWorkspace.jsx'
import { CurrentSiteProvider } from './components/CurrentSiteContext.jsx'

export default function App() {
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    // CURRENT-SITE-02: 현재 Site 선택(메모리 상태, 저장 없음)을 화면 이동 간 유지한다.
    <CurrentSiteProvider>
    <div className="app-shell">
      <Header onMenuClick={() => setMenuOpen((v) => !v)} />
      <div className="app-body">
        <Sidebar open={menuOpen} onNavigate={() => setMenuOpen(false)} />
        <main className="main-content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/scheduler" element={<Scheduler />} />
            <Route path="/calculator-scheduler" element={<CalculatorScheduler />} />
            <Route path="/blog-scheduler" element={<BlogScheduler />} />
            <Route path="/calculators" element={<Calculators />} />
            <Route path="/calculators/:slug" element={<CalculatorDetail />} />
            <Route path="/costs" element={<Cost />} />
            <Route path="/logs" element={<Logs />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/health" element={<Health />} />
            <Route path="/publish" element={<Publish />} />
            <Route path="/trash" element={<Trash />} />
            <Route path="/blog" element={<Blog />} />
            <Route path="/strategy-room" element={<StrategyRoom />} />
            <Route path="/workboard" element={<Workboard />} />
            <Route path="/sites" element={<Sites />} />
            <Route path="/site-wizard" element={<SiteWizard />} />
            <Route path="/assistant" element={<AiAssistant />} />
            <Route path="/ai-workspace" element={<AiWorkspace />} />
          </Routes>
        </main>
      </div>
    </div>
    </CurrentSiteProvider>
  )
}
