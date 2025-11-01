"use client";

import React, { useState, useEffect, useRef, useCallback } from 'react';
import './app.css';

// --- Configuration (from your <script>) ---
const BUBBLE_LIFETIME = 10000;
const FADE_DURATION = 2000;
const MAX_BUBBLES = 50;
const LEADERBOARD_SIZE = 10;
const EVENTSTREAM_URL = 'https://stream.wikimedia.org/v2/stream/recentchange';
const BUBBLE_DELAY = 1500; // Delay between processing queue items

// --- Type Definitions (for TypeScript) ---

// The raw data from Wikipedia's stream
interface WikiEditData {
  id: number;
  wiki: string;
  namespace: number;
  type: string;
  title: string;
  comment: string;
  timestamp: number;
  user: string;
  bot: boolean;
  length?: {
    old: number;
    new: number;
  };
}

// State for a bubble in the visualization
interface BubbleState {
  id: string;
  title: string;
  user: string;
  changeSize: number;
  size: 'large' | 'medium' | 'small' | 'tiny';
  colorClass: string;
  x: number;
  y: number;
  state: 'appearing' | 'visible' | 'fading';
  // Store the raw data for the tooltip
  rawData: WikiEditData; 
}

// State for a headline in the leaderboard
interface HeadlineState {
  id: string;
  title: string;
  user: string;
  changeSize: number;
  timestamp: Date;
  wiki: string;
  comment: string;
}

// State for the connection and stats
type ConnectionStatus = 'connecting' | 'connected' | 'disconnected';
interface StatsState {
  totalEdits: number;
  queueCount: number;
  lastEdit: string;
}

// --- Utility Functions ---

const sizeMap = {
  'large': 200,
  'medium': 150,
  'small': 100,
  'tiny': 70
};

// Gets size and color based on edit data
function getBubbleStyle(data: WikiEditData, changeSize: number) {
  const absSize = Math.abs(changeSize);
  let size: BubbleState['size'];
  let colorClass: string;

  if (absSize > 1000) size = 'large';
  else if (absSize > 300) size = 'medium';
  else if (absSize > 50) size = 'small';
  else size = 'tiny';

  if (data.bot) {
    colorClass = 'bot';
  } else if (data.user && !data.user.includes(':')) { // Registered user
    if (changeSize > 500) colorClass = 'large-positive';
    else if (changeSize > 0) colorClass = 'positive';
    else if (changeSize < -500) colorClass = 'large-negative';
    else if (changeSize < 0) colorClass = 'negative';
    else colorClass = 'neutral';
  } else { // Anonymous user
    colorClass = 'anon';
  }

  return { size, colorClass };
}

// Checks for overlap against existing bubbles (now state-driven)
function checkOverlap(newPos: { x: number, y: number, radius: number }, existingBubbles: BubbleState[]) {
  for (const bubble of existingBubbles) {
    const existingRadius = sizeMap[bubble.size] / 2;
    const existingX = bubble.x + existingRadius;
    const existingY = bubble.y + existingRadius;

    const newX = newPos.x + newPos.radius;
    const newY = newPos.y + newPos.radius;

    const dx = newX - existingX;
    const dy = newY - existingY;
    const distance = Math.sqrt(dx * dx + dy * dy);
    const minDistance = newPos.radius + existingRadius + 10; // 10px buffer

    if (distance < minDistance) {
      return true; // Overlap
    }
  }
  return false; // No overlap
}

// Gets a random non-overlapping position
function getRandomPosition(
  containerEl: HTMLDivElement | null,
  size: BubbleState['size'], 
  existingBubbles: BubbleState[]
): { x: number, y: number } | null {
  if (!containerEl) return null;

  const rect = containerEl.getBoundingClientRect();
  const bubbleSize = sizeMap[size];
  const radius = bubbleSize / 2;
  const maxX = rect.width - bubbleSize - 40; // 20px padding
  const maxY = rect.height - bubbleSize - 40;

  if (maxX <= 0 || maxY <= 0) return null; // Container too small

  let attempts = 0;
  const maxAttempts = 100;
  
  while (attempts < maxAttempts) {
    const pos = {
      x: Math.random() * maxX + 20,
      y: Math.random() * maxY + 20,
      radius: radius
    };

    if (!checkOverlap(pos, existingBubbles)) {
      return pos;
    }
    attempts++;
  }
  // Fallback: just return the last position if we failed to find a good spot
  return { x: Math.random() * maxX + 20, y: Math.random() * maxY + 20 };
}

// Formats time for the leaderboard
function getTimeAgo(timestamp: Date, now: Date) {
  const seconds = Math.floor((now.getTime() - timestamp.getTime()) / 1000);
  if (seconds < 10) return 'just now';
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ago`;
}

// Sanitizes text for display
function escapeHtml(text: string) {
  if (typeof text !== 'string') return '';
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// --- The Main App Component ---

function App() {
  // --- State ---
  const [status, setStatus] = useState<{ type: ConnectionStatus, text: string }>({
    type: 'connecting',
    text: 'Connecting to Wikipedia EventStreams...'
  });
  const [stats, setStats] = useState<StatsState>({
    totalEdits: 0,
    queueCount: 0,
    lastEdit: '-'
  });
  const [headlines, setHeadlines] = useState<HeadlineState[]>([]);
  const [bubbles, setBubbles] = useState<BubbleState[]>([]);
  const [tooltip, setTooltip] = useState({
    visible: false,
    content: '',
    x: 0,
    y: 0
  });
  // This state triggers a re-render to update "time ago"
  const [now, setNow] = useState(() => new Date()); 

  // --- Refs ---
  const visContainerRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const bubbleQueueRef = useRef<WikiEditData[]>([]);
  const isProcessingQueueRef = useRef(false);

  // --- Core Logic (Callbacks) ---

  // MODIFIED: This function now accepts a 'headline' string
  const addBubble = useCallback((data: WikiEditData, changeSize: number, headline: string) => {
    setBubbles(prevBubbles => {
      const { size, colorClass } = getBubbleStyle(data, changeSize);
      
      const position = getRandomPosition(visContainerRef.current, size, prevBubbles);
      if (!position) return prevBubbles; // Failed to place

      const newBubble: BubbleState = {
        id: `bubble-${data.id}-${Math.random()}`,
        title: headline, // <-- USES THE GENERATED HEADLINE
        user: data.user || 'Anonymous',
        changeSize: changeSize,
        size: size,
        colorClass: colorClass,
        x: position.x,
        y: position.y,
        state: 'appearing',
        rawData: data // <-- Tooltip can still access original data
      };

      // Set timers to fade and remove the bubble
      setTimeout(() => {
        setBubbles(prev => 
          prev.map(b => b.id === newBubble.id ? { ...b, state: 'fading' } : b)
        );
      }, BUBBLE_LIFETIME);

      setTimeout(() => {
        setBubbles(prev => prev.filter(b => b.id !== newBubble.id));
      }, BUBBLE_LIFETIME + FADE_DURATION);

      // Add new bubble and manage max bubbles
      const updatedBubbles = [...prevBubbles, newBubble];
      if (updatedBubbles.length > MAX_BUBBLES) {
        return updatedBubbles.slice(1); // Remove oldest
      }
      return updatedBubbles;
    });
  }, []); // Empty dependency array, safe because it uses state setters

  // MODIFIED: This function now accepts a 'headline' string
  const addHeadline = useCallback((data: WikiEditData, changeSize: number, headline: string) => {
    const newHeadline: HeadlineState = {
      id: `headline-${data.id}-${Math.random()}`,
      title: headline, // <-- USES THE GENERATED HEADLINE
      user: data.user || 'Anonymous',
      changeSize: changeSize,
      timestamp: new Date(data.timestamp * 1000),
      wiki: data.wiki,
      comment: data.comment || ''
    };

    // Add new headline to start, and trim to LEADERBOARD_SIZE
    setHeadlines(prev => [newHeadline, ...prev].slice(0, LEADERBOARD_SIZE));
  }, []); // Empty dependency array

  // MODIFIED: This function is now async and calls the API
  const processEdit = useCallback(async (data: WikiEditData) => { // <-- 1. Make it async
    const changeSize = (data.length?.new || 0) - (data.length?.old || 0);
    let headlineToUse = data.title; // Default to the original title as a fallback

    try {
      // 2. Call your new API route
      const response = await fetch('/api/generate-headline', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: data.title,
          user: data.user,
          comment: data.comment
        })
      });

      if (response.ok) {
        const { headline } = await response.json();
        headlineToUse = headline; // Use the AI-generated headline
      } else {
        console.error('API Error, using fallback title');
      }
    } catch (error) {
      console.error('Failed to fetch headline, using fallback title:', error);
      // Fallback: headlineToUse is already set to data.title
    }

    // 3. Pass the (new or fallback) headline to your functions
    addBubble(data, changeSize, headlineToUse);
    addHeadline(data, changeSize, headlineToUse);

    // 4. Update stats (this is not async, so it's fine)
    setStats(prev => ({
      ...prev,
      totalEdits: prev.totalEdits + 1,
      lastEdit: new Date().toLocaleTimeString()
    }));

  }, [addBubble, addHeadline]); // Dependencies are correct

  // This function processes the queue with a delay
  const processQueue = useCallback(() => {
    if (isProcessingQueueRef.current || bubbleQueueRef.current.length === 0) {
      return;
    }

    isProcessingQueueRef.current = true;
    
    const data = bubbleQueueRef.current.shift(); // Get item from front
    setStats(prev => ({ ...prev, queueCount: bubbleQueueRef.current.length }));

    if (data) {
      // processEdit is async, but we don't need to 'await' it here.
      // We want it to fire and then let the timeout schedule the next one.
      processEdit(data);
    }

    // Schedule next processing
    setTimeout(() => {
      isProcessingQueueRef.current = false;
      processQueue(); // Check queue again
    }, BUBBLE_DELAY);

  }, [processEdit]); // Depends on processEdit

  // --- Effects ---

  // 1. Effect to connect to Wikipedia EventStream
  useEffect(() => {
    try {
      const eventSource = new EventSource(EVENTSTREAM_URL);
      eventSourceRef.current = eventSource;

      eventSource.onopen = () => {
        setStatus({ type: 'connected', text: 'Connected to Wikipedia EventStreams' });
        console.log('✅ Connected to Wikipedia EventStreams');
      };

      eventSource.onerror = (error) => {
        setStatus({ type: 'disconnected', text: 'Connection error - Reconnecting...' });
        console.error('❌ EventStream error:', error);
      };

      eventSource.onmessage = (event) => {
        try {
          const data: WikiEditData = JSON.parse(event.data);

          // Filter for meaningful content
          if (data.wiki === 'enwiki' &&
              data.namespace === 0 &&
              data.type === 'edit' &&
              data.title &&
              !data.bot &&
              data.title.length > 3 &&
              Math.abs((data.length?.new || 0) - (data.length?.old || 0)) > 20) 
          {
            bubbleQueueRef.current.push(data);
            setStats(prev => ({ ...prev, queueCount: bubbleQueueRef.current.length }));
            processQueue(); // Start processing if not already
          }
        } catch (error) {
          console.error('Error parsing event:', error);
        }
      };

    } catch (error) {
      console.error('Failed to connect:', error);
      setStatus({ type: 'disconnected', text: 'Failed to connect' });
    }

    // Cleanup function to close the connection on component unmount
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        console.log('🛑 EventStream connection closed');
      }
    };
  }, [processQueue]); // Re-run if processQueue (by reference) changes

  // 2. Effect to update the "time ago" ticker
  useEffect(() => {
    const timer = setInterval(() => {
      setNow(new Date());
    }, 10000); // Update every 10 seconds
    
    return () => clearInterval(timer); // Cleanup
  }, []);


  // --- Tooltip Handlers ---

  const handleShowTooltip = (e: React.MouseEvent, bubble: BubbleState) => {
    const data = bubble.rawData; // Use the original data for the tooltip
    const changeText = bubble.changeSize > 0 ? `+${bubble.changeSize}` : bubble.changeSize;
    
    setTooltip({
      visible: true,
      x: e.pageX + 15,
      y: e.pageY + 15,
      content: `
        <strong>${escapeHtml(data.title)}</strong><br>
        <strong>User:</strong> ${escapeHtml(data.user || 'Anonymous')}<br>
        <strong>Change:</strong> ${changeText} bytes<br>
        <strong>Wiki:</strong> ${data.wiki || 'unknown'}<br>
        ${data.comment ? `<strong>Comment:</strong> ${escapeHtml(data.comment.substring(0, 100))}` : ''}
      `
    });
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (tooltip.visible) {
      setTooltip(prev => ({ ...prev, x: e.pageX + 15, y: e.pageY + 15 }));
    }
  };

  const handleHideTooltip = () => {
    setTooltip(prev => ({ ...prev, visible: false }));
  };

  // --- Render ---

  return (
    <>
      {/* Tooltip (renders at root) */}
      {tooltip.visible && (
        <div
          className="tooltip"
          style={{ display: 'block', left: tooltip.x, top: tooltip.y }}
          dangerouslySetInnerHTML={{ __html: tooltip.content }}
        />
      )}

      {/* Main Container */}
      <div className="container" onMouseMove={handleMouseMove}>
        
        {/* Leaderboard Sidebar */}
        <div className="leaderboard" id="leaderboard">
          <h2>📊 Live Headlines</h2>
          <div id="leaderboard-items">
            {headlines.length === 0 && (
              <div style={{ padding: '20px', textAlign: 'center', color: '#666', fontSize: '14px' }}>
                Connecting to Wikipedia...
              </div>
            )}
            {headlines.map((headline, index) => {
              const timeAgo = getTimeAgo(headline.timestamp, now);
              const changeText = headline.changeSize > 0 ? `+${headline.changeSize}` : headline.changeSize;
              const changeColor = headline.changeSize > 0 ? '#5a7eb8' : headline.changeSize < 0 ? '#c94343' : '#d4a853';

              return (
                <div className="leaderboard-item" data-headline-id={headline.id} data-rank={index + 1} key={headline.id}>
                  <div className="leaderboard-rank">#{index + 1}</div>
                  <div className="leaderboard-headline">{escapeHtml(headline.title)}</div>
                  <div className="leaderboard-meta">
                    <span 
                      className="leaderboard-badge edits" 
                      style={{ backgroundColor: `${changeColor}20`, color: changeColor }}
                    >
                      {changeText} bytes
                    </span>
                    <span className="leaderboard-badge time">
                      🕐 {timeAgo}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Main Content */}
        <div className="main-content">
          <h1>WIKI-NEWS</h1>
          <p className="subtitle">real-time wikipedia article edits visualization</p>

          <div className="status-bar">
            <div className={`status-indicator ${status.type}`} id="status-indicator"></div>
            <span id="status-text">{status.text}</span>
          </div>

          <div className="visualization-container" ref={visContainerRef}>
            {bubbles.map(bubble => (
              <div
                key={bubble.id}
                className={`bubble ${bubble.size} ${bubble.colorClass} ${bubble.state === 'fading' ? 'fading' : ''}`}
                style={{ left: bubble.x, top: bubble.y }}
                onMouseEnter={(e) => handleShowTooltip(e, bubble)}
                onMouseLeave={handleHideTooltip}
              >
                {/* Display the AI-generated headline in the bubble */}
                {bubble.size !== 'tiny' ? bubble.title : ''}
              </div>
            ))}
          </div>

          <div className="stats">
            <div className="stat-box">
              <strong id="edit-count">{stats.totalEdits}</strong> edits received
            </div>
            <div className="stat-box">
              {/* Active count is now just the length of the bubbles array */}
              <strong id="active-count">{bubbles.length}</strong> active bubbles
            </div>
            <div className="stat-box">
              <strong id="queue-count">{stats.queueCount}</strong> in queue
            </div>
            <div className="stat-box">
              Last edit: <strong id="last-edit">{stats.lastEdit}</strong>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

export default App;