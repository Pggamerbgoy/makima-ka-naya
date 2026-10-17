import { useCallback, useEffect, useRef, useState } from 'react';
import { websocketUrl } from '../api';
import type { StreamEvent } from '../types';

export type ConnectionState = 'idle' | 'connecting' | 'connected' | 'reconnecting' | 'offline';
export type TaskState = 'idle' | 'running' | 'interrupted' | 'completed' | 'error' | 'cancelled';

type Options = {
  configuredUrl: string;
  onEvent: (event: StreamEvent) => void;
  onNotice?: (message: string) => void;
};

export function useMakimaSocket({ configuredUrl, onEvent, onNotice }: Options) {
  const socket = useRef<WebSocket | null>(null);
  const timers = useRef<number[]>([]);
  const heartbeat = useRef<number | undefined>(undefined);
  const intentionalClose = useRef(false);
  const retryCount = useRef(0);
  const generation = useRef(0);
  const onEventRef = useRef(onEvent);
  const onNoticeRef = useRef(onNotice);
  const activeTaskRef = useRef<string | null>(null);
  const [connectionState, setConnectionState] = useState<ConnectionState>('idle');
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [interruptedTaskId, setInterruptedTaskId] = useState<string | null>(null);
  const [taskState, setTaskState] = useState<TaskState>('idle');
  const [taskStage, setTaskStage] = useState('');

  useEffect(() => { onEventRef.current = onEvent; onNoticeRef.current = onNotice; }, [onEvent, onNotice]);
  useEffect(() => { activeTaskRef.current = activeTaskId; }, [activeTaskId]);

  const clearTimers = useCallback(() => {
    timers.current.forEach((timer) => window.clearTimeout(timer));
    timers.current = [];
    if (heartbeat.current) window.clearInterval(heartbeat.current);
    heartbeat.current = undefined;
  }, []);

  const connect = useCallback(() => {
    clearTimers();
    const currentGeneration = generation.current + 1;
    generation.current = currentGeneration;
    intentionalClose.current = false;
    socket.current?.close();
    setConnectionState(retryCount.current ? 'reconnecting' : 'connecting');
    const ws = new WebSocket(websocketUrl(configuredUrl));
    socket.current = ws;
    ws.onopen = () => {
      if (currentGeneration !== generation.current) return;
      retryCount.current = 0;
      setConnectionState('connected');
      heartbeat.current = window.setInterval(() => { if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' })); }, 20_000);
    };
    ws.onmessage = (message) => {
      if (currentGeneration !== generation.current) return;
      try {
        const event = JSON.parse(String(message.data)) as StreamEvent;
        const taskId = String(event.task_id ?? '');
        if (event.type === 'status' && taskId === activeTaskRef.current) setTaskStage(String(event.stage ?? 'working'));
        if (event.type === 'message' && taskId === activeTaskRef.current) { setTaskState('completed'); setActiveTaskId(null); }
        if (event.type === 'error' && taskId === activeTaskRef.current) { setTaskState('error'); setActiveTaskId(null); }
        if (event.type === 'task_cancelled' && taskId === activeTaskRef.current) { setTaskState('cancelled'); setActiveTaskId(null); }
        onEventRef.current(event);
      } catch { onEventRef.current({ type: 'protocol_error', message: 'Malformed server event.' }); }
    };
    ws.onerror = () => { if (currentGeneration !== generation.current) return; setConnectionState('offline'); onNoticeRef.current?.('Local Makima server connection failed.'); };
    ws.onclose = () => {
      if (currentGeneration !== generation.current) return;
      clearTimers();
      if (intentionalClose.current) return;
      if (activeTaskRef.current) { setInterruptedTaskId(activeTaskRef.current); setTaskState('interrupted'); setActiveTaskId(null); }
      setConnectionState('reconnecting');
      const delay = Math.min(8_000, 750 * (2 ** retryCount.current));
      retryCount.current += 1;
      timers.current.push(window.setTimeout(connect, delay));
    };
  }, [clearTimers, configuredUrl]);

  useEffect(() => {
    connect();
    return () => { intentionalClose.current = true; clearTimers(); socket.current?.close(); socket.current = null; };
  }, [clearTimers, connect]);

  const send = useCallback((payload: string, taskId?: string) => {
    if (socket.current?.readyState !== WebSocket.OPEN) return false;
    if (taskId) { setInterruptedTaskId(null); setActiveTaskId(taskId); setTaskState('running'); setTaskStage('sending'); }
    socket.current.send(payload);
    return true;
  }, []);

  const stop = useCallback(() => {
    if (!activeTaskId || socket.current?.readyState !== WebSocket.OPEN) return false;
    socket.current.send(JSON.stringify({ type: 'cancel_task', task_id: activeTaskId }));
    setTaskStage('cancelling');
    return true;
  }, [activeTaskId]);

  const reconnect = useCallback(() => { retryCount.current = 0; connect(); }, [connect]);

  return { connectionState, activeTaskId, interruptedTaskId, taskState, taskStage, send, stop, reconnect };
}
