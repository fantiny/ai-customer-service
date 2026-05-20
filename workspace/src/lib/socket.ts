import { io, Socket } from 'socket.io-client';
import { getStoredToken } from './auth';

/**
 * Create the Socket.io client with JWT auth.
 *
 * The token is passed in the Socket.io handshake `auth` object so the server
 * can verify it in the `connect` event handler before accepting the connection.
 *
 * If no token is stored (guest mode), `auth.token` is omitted and the server
 * falls back to guest mode (when JWT_REQUIRED=False).
 */
function createSocket(): Socket {
  const token = getStoredToken();
  // In production, connect to the backend URL directly (cross-origin).
  // In dev, connect to '/' so Vite proxy forwards to localhost:8000.
  const serverUrl = (import.meta.env.VITE_API_BASE_URL as string) || '/';
  return io(serverUrl, {
    path: '/socket.io',
    transports: ['websocket', 'polling'],
    autoConnect: true,
    auth: token ? { token } : {},
  });
}

const socket: Socket = createSocket();

/**
 * Reconnect the socket with a fresh token.
 * Call this after login/logout to re-authenticate.
 */
export function reconnectWithToken(): void {
  const token = getStoredToken();
  socket.auth = token ? { token } : {};
  if (socket.connected) {
    socket.disconnect();
  }
  socket.connect();
}

export default socket;
