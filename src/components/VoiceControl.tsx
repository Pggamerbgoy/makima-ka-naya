import { useCallback, useEffect, useRef, useState } from 'react';
import { Mic, Radio, Sparkles, Square, Volume2, Waves } from 'lucide-react';
import type { UiSettings } from '../types';
import { websocketUrl } from '../api';
import { Button } from './ui';

type SpeechRecognitionResultItem = { transcript: string; confidence?: number };
type SpeechRecognitionResult = ArrayLike<SpeechRecognitionResultItem> & { isFinal?: boolean };
type SpeechRecognitionEvent = { results: ArrayLike<SpeechRecognitionResult> };

type WakeRecognizer = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  onend: (() => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  start: () => void;
  stop: () => void;
  abort?: () => void;
};
type WakeRecognizerCtor = new () => WakeRecognizer;

type VoiceState = 'off' | 'ambient' | 'live' | 'speaking' | 'followup' | 'error';

function playAudioChime(type: 'wake' | 'standby' | 'success'): void {
  try {
    const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.connect(gain);
    gain.connect(ctx.destination);
    const now = ctx.currentTime;
    if (type === 'wake') {
      osc.frequency.setValueAtTime(880, now);
      osc.frequency.exponentialRampToValueAtTime(1320, now + 0.12);
      gain.gain.setValueAtTime(0.18, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.28);
      osc.start(now);
      osc.stop(now + 0.28);
    } else if (type === 'success') {
      osc.frequency.setValueAtTime(660, now);
      osc.frequency.exponentialRampToValueAtTime(1100, now + 0.08);
      gain.gain.setValueAtTime(0.14, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.2);
      osc.start(now);
      osc.stop(now + 0.2);
    } else {
      osc.frequency.setValueAtTime(1320, now);
      osc.frequency.exponentialRampToValueAtTime(880, now + 0.14);
      gain.gain.setValueAtTime(0.12, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.32);
      osc.start(now);
      osc.stop(now + 0.32);
    }
  } catch {
    // AudioContext blocked
  }
}

function downsamplePcm(input: Float32Array, fromRate: number, toRate = 16000): ArrayBuffer {
  const ratio = fromRate / toRate;
  const output = new Int16Array(Math.round(input.length / ratio));
  for (let index = 0; index < output.length; index += 1) {
    output[index] = Math.max(-1, Math.min(1, input[Math.min(Math.floor(index * ratio), input.length - 1)])) * 0x7fff;
  }
  return output.buffer;
}

export function VoiceControl({
  settings,
  onNotice,
  onVoiceCommand,
}: {
  settings: UiSettings;
  onNotice?: (message: string) => void;
  onVoiceCommand?: (command: string, autoSend?: boolean) => void;
}) {
  const [state, setState] = useState<VoiceState>('off');
  const [notice, setNotice] = useState('Jarvis: Say “Makima” or tap to speak');
  const [liveTranscript, setLiveTranscript] = useState('');
  const [followupSeconds, setFollowupSeconds] = useState(0);

  const socket = useRef<WebSocket | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const audioContext = useRef<AudioContext | null>(null);
  const processor = useRef<ScriptProcessorNode | null>(null);
  const wake = useRef<WakeRecognizer | null>(null);
  const voiceReady = useRef(false);
  const nextAudioTime = useRef(0);
  const isSpeaking = useRef(false);
  const stateRef = useRef<VoiceState>('off');
  const followupTimer = useRef<number | null>(null);
  const activeAudioSources = useRef<AudioBufferSourceNode[]>([]);
  const isIntentDispatchedRef = useRef(false);

  stateRef.current = state;

  const notify = useCallback((message: string, isToast = false) => {
    setNotice(message);
    if (isToast) onNotice?.(message);
  }, [onNotice]);

  const dispatchVoiceCommand = useCallback((spokenText: string) => {
    const raw = spokenText.trim();
    if (!raw) return;
    const lower = raw.toLowerCase();

    playAudioChime('success');
    notify(`Heard: "${raw}"`);

    // Shortcut dispatching
    if (lower.includes('clear chat') || lower.includes('delete chat') || lower.includes('nayi chat') || lower.includes('new chat')) {
      onVoiceCommand?.('__CLEAR_CHAT__', false);
      notify('Chat session cleared');
    } else if (lower.includes('toggle theme') || lower.includes('dark mode') || lower.includes('light mode') || lower.includes('day mode')) {
      onVoiceCommand?.('__TOGGLE_THEME__', false);
      notify('Theme toggled');
    } else if (lower.includes('check git') || lower.includes('git status') || lower.includes('git diff')) {
      onVoiceCommand?.('Check local Git repository status and show recent uncommitted diffs', true);
    } else if (lower.includes('free port') || lower.includes('kill port') || lower.includes('port 3000')) {
      onVoiceCommand?.('Check if port 3000 or 8080 is occupied, and identify or free the process', true);
    } else if (lower.includes('tile window') || lower.includes('snap window') || lower.includes('split window')) {
      onVoiceCommand?.('Snap active window to the left 50% and browser to the right 50%', true);
    } else if (lower.includes('clipboard') || lower.includes('read clipboard')) {
      onVoiceCommand?.('Read current text from my OS clipboard and format it as markdown', true);
    } else {
      // General prompt command
      onVoiceCommand?.(raw, true);
    }
  }, [notify, onVoiceCommand]);

  const stopAudioSources = useCallback(() => {
    activeAudioSources.current.forEach((src) => {
      try { src.stop(); } catch { /* already stopped */ }
    });
    activeAudioSources.current = [];
    isSpeaking.current = false;
    nextAudioTime.current = 0;
  }, []);

  const stopWake = useCallback(() => {
    if (wake.current) {
      wake.current.onend = null;
      wake.current.onerror = null;
      wake.current.onresult = null;
      try { wake.current.stop(); } catch { /* already stopped */ }
      wake.current = null;
    }
  }, []);

  const stopLive = useCallback(() => {
    if (followupTimer.current !== null) {
      window.clearInterval(followupTimer.current);
      followupTimer.current = null;
    }
    voiceReady.current = false;
    stopAudioSources();
    processor.current?.disconnect();
    processor.current = null;
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
    if (audioContext.current?.state !== 'closed') {
      audioContext.current?.close().catch(() => {});
    }
    audioContext.current = null;
    if (socket.current?.readyState === WebSocket.OPEN) {
      socket.current.send(JSON.stringify({ type: 'stop' }));
    }
    socket.current?.close();
    socket.current = null;
    stopWake();
    setState('off');
    setLiveTranscript('');
    notify('Jarvis paused — tap to start');
  }, [notify, stopAudioSources, stopWake]);

  const playPcm = useCallback(async (payload: ArrayBuffer | Blob) => {
    const bytes = payload instanceof Blob ? await payload.arrayBuffer() : payload;
    const context = audioContext.current;
    if (!context || context.state === 'closed') return;
    const pcm = new Int16Array(bytes);
    const buffer = context.createBuffer(1, pcm.length, 24000);
    const channel = buffer.getChannelData(0);
    pcm.forEach((value, index) => {
      channel[index] = value / 0x7fff;
    });
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    const startAt = Math.max(context.currentTime, nextAudioTime.current);
    source.start(startAt);
    nextAudioTime.current = startAt + buffer.duration;

    isSpeaking.current = true;
    setState('speaking');
    notify('Makima is speaking…');

    activeAudioSources.current.push(source);
    source.onended = () => {
      activeAudioSources.current = activeAudioSources.current.filter((s) => s !== source);
      if (activeAudioSources.current.length === 0) {
        isSpeaking.current = false;
      }
    };
  }, [notify]);

  // Ambient wake listener with continuous speech command extraction
  const startAmbient = useCallback(() => {
    stopLive();
    const constructor = (window as unknown as { SpeechRecognition?: WakeRecognizerCtor; webkitSpeechRecognition?: WakeRecognizerCtor }).SpeechRecognition ||
      (window as unknown as { webkitSpeechRecognition?: WakeRecognizerCtor }).webkitSpeechRecognition;

    if (!constructor) {
      notify('Speech recognition unavailable in this browser');
      return;
    }

    const recognizer = new constructor();
    recognizer.continuous = true;
    recognizer.interimResults = true;
    recognizer.lang = settings.language === 'hi' ? 'hi-IN' : 'en-US';

    const wakeWords = (settings.wake_words && settings.wake_words.length > 0)
      ? settings.wake_words.map((w) => w.trim().toLowerCase())
      : ['makima', 'hey makima', 'jarvis', 'suno makima'];

    recognizer.onresult = (event) => {
      let finalTranscript = '';
      let interimTranscript = '';

      for (let i = 0; i < event.results.length; i += 1) {
        const item = event.results[i][0];
        if (event.results[i].isFinal) {
          finalTranscript += ` ${item.transcript}`;
        } else {
          interimTranscript += ` ${item.transcript}`;
        }
      }

      const fullText = (finalTranscript || interimTranscript).trim().toLowerCase();
      if (!fullText) return;

      // Check for wake words
      for (const word of wakeWords) {
        const idx = fullText.indexOf(word);
        if (idx !== -1) {
          const commandAfterWake = fullText.slice(idx + word.length).trim().replace(/^[,.:!?-]+/, '').trim();
          if (commandAfterWake.length >= 3 && !isIntentDispatchedRef.current) {
            isIntentDispatchedRef.current = true;
            dispatchVoiceCommand(commandAfterWake);
            window.setTimeout(() => { isIntentDispatchedRef.current = false; }, 2000);
            return;
          }
          if (stateRef.current !== 'live' && stateRef.current !== 'speaking') {
            playAudioChime('wake');
            setState('live');
            notify('Listening for your command…');
            return;
          }
        }
      }

      // If already in live mode and user speaks a command
      if (stateRef.current === 'live' && fullText.length > 3 && !isIntentDispatchedRef.current) {
        setLiveTranscript(fullText);
        if (event.results[event.results.length - 1].isFinal) {
          isIntentDispatchedRef.current = true;
          dispatchVoiceCommand(fullText);
          window.setTimeout(() => {
            isIntentDispatchedRef.current = false;
            setLiveTranscript('');
            setState('ambient');
          }, 1800);
        }
      }
    };

    recognizer.onerror = (ev) => {
      if (ev.error === 'no-speech' || ev.error === 'aborted') {
        return;
      }
      notify('Jarvis auto-reconnecting…');
    };

    recognizer.onend = () => {
      // Seamless auto-reconnect watchdog so listening never terminates
      if (stateRef.current === 'ambient' || stateRef.current === 'off' || settings.jarvis_mode) {
        window.setTimeout(() => {
          if (wake.current === recognizer) {
            try { recognizer.start(); } catch { /* restarting */ }
          }
        }, 180);
      }
    };

    wake.current = recognizer;
    try {
      recognizer.start();
      setState('ambient');
      notify('Jarvis listening for “Makima” / “Jarvis”');
    } catch {
      notify('Tap to allow microphone');
    }
  }, [dispatchVoiceCommand, notify, settings.jarvis_mode, settings.language, settings.wake_words, stopLive]);

  const startFollowupWindow = useCallback(() => {
    const totalSeconds = Math.max(5, settings.followup_window_s || 10);
    setFollowupSeconds(totalSeconds);
    setState('followup');
    notify(`Follow-up window (${totalSeconds}s) — ask another question`);

    if (followupTimer.current !== null) {
      window.clearInterval(followupTimer.current);
    }

    let remaining = totalSeconds;
    followupTimer.current = window.setInterval(() => {
      remaining -= 1;
      setFollowupSeconds(remaining);
      if (remaining <= 0) {
        if (followupTimer.current !== null) {
          window.clearInterval(followupTimer.current);
          followupTimer.current = null;
        }
        playAudioChime('standby');
        notify('Returning to ambient guard…');
        startAmbient();
      } else {
        notify(`Follow-up window (${remaining}s) — ask another question`);
      }
    }, 1000);
  }, [notify, settings.followup_window_s, startAmbient]);

  const startLive = useCallback(async () => {
    try {
      if (followupTimer.current !== null) {
        window.clearInterval(followupTimer.current);
        followupTimer.current = null;
      }
      stopWake();
      notify('Activating voice stream…');

      const media = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      stream.current = media;
      const context = new AudioContext();
      await context.resume();
      audioContext.current = context;

      // Try connecting to Gemini Live backend
      try {
        const ws = new WebSocket(websocketUrl('/ws/voice'));
        ws.binaryType = 'arraybuffer';
        socket.current = ws;

        ws.onopen = () => {
          ws.send(JSON.stringify({
            type: 'start',
            model: 'gemini-3.8-live',
            voice_name: settings.voice_name || 'Aoede',
          }));
        };

        ws.onmessage = (event) => {
          if (typeof event.data !== 'string') {
            void playPcm(event.data);
            return;
          }
          try {
            const message = JSON.parse(event.data) as { type: string; message?: string; text?: string };
            if (message.type === 'voice_ready') {
              voiceReady.current = true;
              setState('live');
              notify('Listening — speak your command');
            } else if (message.type === 'text') {
              notify(message.text || 'Listening…');
            } else if (message.type === 'turn_complete') {
              startFollowupWindow();
            } else if (message.type === 'interrupted') {
              stopAudioSources();
              setState('live');
              notify('Listening to you…');
            } else if (message.type === 'voice_error') {
              startAmbient();
            }
          } catch {
            startAmbient();
          }
        };

        ws.onerror = () => {
          // If websocket fails, gracefully fall back to Web Speech recognition
          startAmbient();
        };
      } catch {
        startAmbient();
      }

      const source = context.createMediaStreamSource(media);
      const node = context.createScriptProcessor(4096, 1, 1);
      const silent = context.createGain();
      silent.gain.value = 0;
      source.connect(node);
      node.connect(silent);
      silent.connect(context.destination);

      node.onaudioprocess = (event) => {
        const inputData = event.inputBuffer.getChannelData(0);
        let sumSquares = 0;
        for (let i = 0; i < inputData.length; i += 1) {
          sumSquares += inputData[i] * inputData[i];
        }
        const rms = Math.sqrt(sumSquares / inputData.length);

        if (isSpeaking.current && rms > 0.04) {
          stopAudioSources();
          setState('live');
          notify('Listening to you…');
        }

        if (stateRef.current === 'followup' && rms > 0.035) {
          if (followupTimer.current !== null) {
            window.clearInterval(followupTimer.current);
            followupTimer.current = null;
          }
          setState('live');
          notify('Listening to follow-up…');
        }

        if (voiceReady.current && socket.current?.readyState === WebSocket.OPEN) {
          socket.current.send(downsamplePcm(inputData, context.sampleRate));
        }
      };

      processor.current = node;
      setState('live');
      notify('Listening — say your command');
    } catch (error) {
      // Fallback directly to SpeechRecognition if mic stream error
      startAmbient();
    }
  }, [notify, playPcm, settings.voice_name, startAmbient, startFollowupWindow, stopAudioSources, stopWake]);

  useEffect(() => {
    if (settings.jarvis_mode || settings.auto_listen_on_start) {
      startAmbient();
    }
    return () => {
      stopLive();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const active = state === 'ambient' || state === 'live' || state === 'speaking' || state === 'followup';

  const handleClick = () => {
    if (state === 'live' || state === 'speaking' || state === 'followup') {
      startAmbient();
    } else if (state === 'ambient') {
      void startLive();
    } else {
      void startLive();
    }
  };

  const getButtonTitle = () => {
    if (state === 'live') return 'Listening — Click to pause';
    if (state === 'speaking') return 'Speaking — Click to pause';
    if (state === 'followup') return `Follow-up (${followupSeconds}s) — Click for standby`;
    if (state === 'ambient') return 'Jarvis Listening for “Makima” — Click to speak';
    return 'Click to activate voice commands';
  };

  return (
    <div className="voice-control">
      <Button
        className={`voice-button ${active ? `voice-${state}` : ''}`}
        title={getButtonTitle()}
        aria-label={getButtonTitle()}
        onClick={handleClick}
      >
        {state === 'speaking' ? (
          <Volume2 size={15} />
        ) : state === 'followup' ? (
          <Sparkles size={15} />
        ) : state === 'ambient' ? (
          <Radio size={15} />
        ) : (
          <Mic size={15} />
        )}
        <span>
          {state === 'speaking'
            ? 'Speaking'
            : state === 'followup'
            ? `Follow-up ${followupSeconds}s`
            : state === 'live'
            ? 'Listening'
            : state === 'ambient'
            ? 'Jarvis ON'
            : 'Jarvis Voice'}
        </span>
        {active && (
          <span className="voice-wave" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
        )}
      </Button>
      {active && (
        <span className="wake-hint" title={notice}>
          {liveTranscript ? `Heard: "${liveTranscript}"` : notice}
        </span>
      )}
      {state === 'error' && (
        <Button className="voice-retry" onClick={() => void startLive()}>
          <Square size={12} /> Retry
        </Button>
      )}
    </div>
  );
}
