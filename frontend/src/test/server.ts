import { setupServer } from 'msw/node';

// No default handlers: each test declares the API it talks to with server.use().
export const server = setupServer();
