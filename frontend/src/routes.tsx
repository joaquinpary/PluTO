import { Navigate, type RouteObject } from 'react-router-dom';
import { AppLayout } from './components/AppLayout';
import { RequireAuth } from './components/RequireAuth';
import { AccountPage } from './pages/account/AccountPage';
import { BoardDetailPage } from './pages/boards/BoardDetailPage';
import { BoardsPage } from './pages/boards/BoardsPage';
import { HistoryPage } from './pages/history/HistoryPage';
import { HomePage } from './pages/home/HomePage';
import { LoginPage } from './pages/login/LoginPage';
import { LogsPage } from './pages/logs/LogsPage';
import { PluginDetailPage } from './pages/plugins/PluginDetailPage';
import { PluginNewPage } from './pages/plugins/PluginNewPage';
import { PluginsPage } from './pages/plugins/PluginsPage';
import { SetupPage } from './pages/setup/SetupPage';

// One route per screen.
export const routes: RouteObject[] = [
  { path: '/setup', element: <SetupPage /> },
  { path: '/login', element: <LoginPage /> },
  {
    element: <RequireAuth />,
    children: [
      {
        path: '/',
        element: <AppLayout />,
        children: [
          { index: true, element: <HomePage /> },
          { path: 'plugins', element: <PluginsPage /> },
          { path: 'plugins/new', element: <PluginNewPage /> },
          { path: 'plugins/:uuid', element: <PluginDetailPage /> },
          { path: 'boards', element: <BoardsPage /> },
          { path: 'boards/:deviceId', element: <BoardDetailPage /> },
          { path: 'history', element: <HistoryPage /> },
          { path: 'logs', element: <LogsPage /> },
          { path: 'account', element: <AccountPage /> },
          { path: '*', element: <Navigate to="/" replace /> },
        ],
      },
    ],
  },
];
