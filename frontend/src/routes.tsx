import { Navigate, type RouteObject } from 'react-router-dom';
import { AppLayout } from './shared/components/AppLayout';
import { RequireAuth } from './features/auth/RequireAuth';
import { AccountPage } from './features/account/AccountPage';
import { BoardDetailPage } from './features/boards/BoardDetailPage';
import { BoardsPage } from './features/boards/BoardsPage';
import { HistoryPage } from './features/history/HistoryPage';
import { HomePage } from './features/home/HomePage';
import { LoginPage } from './features/auth/LoginPage';
import { LogsPage } from './features/logs/LogsPage';
import { PluginDetailPage } from './features/plugins/PluginDetailPage';
import { PluginNewPage } from './features/plugins/PluginNewPage';
import { PluginsPage } from './features/plugins/PluginsPage';
import { SetupPage } from './features/auth/SetupPage';

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
