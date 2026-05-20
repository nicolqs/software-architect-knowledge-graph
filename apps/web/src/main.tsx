import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import './index.css';
import Layout from './Layout';
import ArchitectPage from './pages/Architect';
import DecisionsPage from './pages/Decisions';
import EchoPage from './pages/Echo';
import GraphPage from './pages/Graph';
import RefactorPage from './pages/Refactor';
import ReviewerPage from './pages/Reviewer';
import StatusPage from './pages/Status';
import TicketsPage from './pages/Tickets';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<StatusPage />} />
          <Route path="/graph" element={<GraphPage />} />
          <Route path="/agents/echo" element={<EchoPage />} />
          <Route path="/agents/architect" element={<ArchitectPage />} />
          <Route path="/agents/tickets" element={<TicketsPage />} />
          <Route path="/agents/reviewer" element={<ReviewerPage />} />
          <Route path="/agents/refactor" element={<RefactorPage />} />
          <Route path="/decisions" element={<DecisionsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
